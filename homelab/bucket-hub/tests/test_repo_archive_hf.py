"""AP-4 ``huggingface_repo`` handler (spec §T3), archiver HF mode and Pi routing.

The model fixture is synthetic: sizes are chosen so pattern filtering changes the outcome.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import repo_archive_hf as hf
from index_writer import load_entries, scrub_free_text, secret_scan
from repo_archive_paths import final_hf_dir, hf_dated_dir, remove_partial_dir
from repo_runner import ArchiverError, RecordingRepoRunner

HUB_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "hf_model_tiny_gpt2.json"
URL = "https://huggingface.co/hf-internal-testing/tiny-random-gpt2"
NOW = datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)
DAY = "2026-10-12"


@pytest.fixture()
def hf_meta():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def hf_env(archive_root, hf_meta, monkeypatch):
    """Archive root + fake runner + metadata stub; returns (runner, updates, calls)."""
    from repo_archive_github import configure as gh_configure

    runner = RecordingRepoRunner(payload_bytes=0)
    gh_configure(runner=runner)
    calls: list[tuple[str, str, str]] = []

    def fetch(repo_type, repo_id, revision):
        calls.append((repo_type, repo_id, revision))
        return hf_meta

    hf.configure(fetch_metadata=fetch)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    # AP-4.3 free-space guard: default to ample space; the dedicated test overrides this.
    monkeypatch.setattr(hf, "_free_space_bytes", lambda _root: 10 * 1024 ** 4)
    updates: list[dict] = []
    return runner, updates, calls


def _run(job, archive_root, updates, ready=(True, "nas")):
    hf.run_huggingface_repo_job(
        job,
        archive_root=archive_root,
        path_ready=lambda _p: ready,
        update_job=lambda jid, **f: updates.append({"id": jid, **f}),
        now=NOW,
    )


def _job(jid="h1", **opts):
    return {"id": jid, "kind": "huggingface_repo", "url": URL, "title": "tiny", "tags": ["hf"], "options": opts}


# --- parsing --------------------------------------------------------------------


def test_repo_id_and_type_from_url():
    assert hf.parse_hf_url(URL) == ("model", "hf-internal-testing/tiny-random-gpt2")
    assert hf.parse_hf_url("https://huggingface.co/datasets/org/data/tree/main") == ("dataset", "org/data")
    assert hf.parse_hf_url("https://huggingface.co/org/name", "dataset") == ("dataset", "org/name")
    assert hf.parse_hf_url("hf:org/name") == ("model", "org/name")
    with pytest.raises(hf.HfRepoError, match="Spaces"):
        hf.parse_hf_url("https://huggingface.co/spaces/org/demo")
    with pytest.raises(hf.HfRepoError):
        hf.parse_hf_url("https://github.com/org/name")
    with pytest.raises(hf.HfRepoError, match="org/name"):
        hf.parse_hf_url("https://huggingface.co/onlyorg")


def test_space_url_job_errors_readably(hf_env, archive_root):
    runner, updates, _ = hf_env
    _run({**_job(), "url": "https://huggingface.co/spaces/org/demo"}, archive_root, updates)
    assert updates[-1]["status"] == "error"
    assert "Spaces" in updates[-1]["error_display"]
    assert not runner.calls


def test_hf_slug_layout(archive_root):
    final = final_hf_dir(hf_dated_dir(archive_root, DAY), "model", "meta-llama/Llama-3.2-1B")
    assert final == archive_root / "huggingface-daily" / DAY / "models__meta-llama__Llama-3.2-1B"


# --- patterns and sizes ---------------------------------------------------------


def test_prefer_safetensors_patterns(hf_meta):
    names = [s["rfilename"] for s in hf_meta["siblings"]]
    allow, ignore = hf.resolve_patterns(names)
    kept = hf.filter_names(names, allow, ignore)
    assert "model.safetensors" in kept
    assert not {"pytorch_model.bin", "tf_model.h5", "flax_model.msgpack"} & set(kept)
    # Explicit allow_patterns win, and the card is always kept.
    allow, ignore = hf.resolve_patterns(names, allow_patterns=["*.bin"])
    assert allow == ["*.bin", "README.md"] and ignore is None
    assert hf.filter_names(names, allow, ignore) == ["README.md", "pytorch_model.bin"]
    # No safetensors in the repo: nothing extra ignored.
    assert hf.resolve_patterns(["pytorch_model.bin"]) == (None, None)
    assert hf.resolve_patterns(names, prefer_safetensors=False) == (None, None)


def test_dir_pattern_matches_like_huggingface_hub():
    assert hf.resolve_patterns([], allow_patterns=["onnx/"])[0] == ["onnx/*", "README.md"]


def test_size_precheck_uses_filtered_siblings(hf_env, archive_root):
    """2 GB .bin would blow a 5 MB cap; prefer_safetensors drops it, so the job proceeds."""
    runner, updates, _ = hf_env
    _run(_job(max_size_mb=5), archive_root, updates)
    assert updates[-1]["status"] == "done", updates[-1]
    assert runner.calls and runner.calls[0]["mode"] == "hf_snapshot"
    spec = runner.calls[0]["spec"]
    assert "*.bin" in spec["ignore_patterns"] and spec["allow_patterns"] is None


def test_size_cap_skip(hf_env, archive_root):
    """AP-4.3: the job itself must read as a skip, never a plain done (the old live bug)."""
    runner, updates, _ = hf_env
    _run(_job(max_size_mb=5, prefer_safetensors=False), archive_root, updates)
    last = updates[-1]
    assert last["status"] == "skipped_too_large", last
    assert last["progress"]["note"].startswith("Skipped:") and "5 MB limit" in last["progress"]["note"]
    assert last["progress"]["source_size_bytes"] > 5 * 1024 * 1024
    assert last["index_entry"]["status"] == "skipped_too_large"
    assert last["index_entry"]["source_size_bytes"] == last["progress"]["source_size_bytes"]
    assert not runner.calls
    rows = list(load_entries(archive_root / "download-index.jsonl").values())
    assert rows[0]["status"] == "skipped_too_large" and rows[0]["source_id"] == "hf:model/hf-internal-testing/tiny-random-gpt2"


def test_size_cap_skip_is_not_a_done_status(hf_env, archive_root):
    """Regression for the live bug (2026-10-12): a ~60 GB paste against the 20 GB default
    showed status "done" in the Hub, indistinguishable from a real finish."""
    runner, updates, _ = hf_env
    _run(_job(max_size_mb=5, prefer_safetensors=False), archive_root, updates)
    assert updates[-1]["status"] != "done"


def test_free_space_guard_defers(hf_env, archive_root, monkeypatch):
    """Not enough free space on the archive volume defers instead of erroring."""
    runner, updates, _ = hf_env
    tiny_free = 1024  # bytes: far below any real model + the 50 GB headroom
    monkeypatch.setattr(hf, "_free_space_bytes", lambda _root: tiny_free)
    _run(_job(prefer_safetensors=False), archive_root, updates)
    last = updates[-1]
    assert last["status"] == "queued"
    assert "not enough space" in (last.get("error_display") or "").lower()
    assert last.get("not_before")
    assert not runner.calls


def test_free_space_bytes_reads_real_disk_usage(tmp_path):
    """_free_space_bytes itself (not the fixture stub) wraps shutil.disk_usage and never raises."""
    assert hf._free_space_bytes(tmp_path) == hf.shutil.disk_usage(str(tmp_path)).free
    assert hf._free_space_bytes(tmp_path / "does-not-exist") is None


# --- errors ---------------------------------------------------------------------


def test_gated_error_text(hf_env, archive_root):
    runner, updates, _ = hf_env
    runner.raise_error = "Access to model is restricted"
    runner.raise_kind = "gated"
    _run(_job(), archive_root, updates)
    assert updates[-1]["status"] == "error"
    assert "accept the licence" in updates[-1]["error_display"]
    assert not list((archive_root / "huggingface-daily" / DAY).glob(".partial-*"))


def test_metadata_not_found_error(hf_env, archive_root):
    runner, updates, _ = hf_env

    def missing(*_a):
        raise ArchiverError("huggingface.co refused model x/y", "not_found")

    hf.configure(fetch_metadata=missing)
    _run(_job(), archive_root, updates)
    assert updates[-1]["error_display"] == hf.NOT_FOUND_MSG
    assert not runner.calls


# --- card -----------------------------------------------------------------------


CARD = """---
license: mit
base_model: openai-community/gpt2
datasets:
  - wikitext
  - "c4"
language: [en, fr]
tags:
- tiny
---

# Tiny model

Use `login(token=hf_abcdefghijklmnopqrstuvwxyz123456)` first.
"""


def test_card_front_matter(hf_env, archive_root):
    runner, updates, _ = hf_env
    runner.hf_files = {"README.md": CARD.encode(), "model.safetensors": b"w" * 4096}
    _run(_job(user_note="test model"), archive_root, updates)
    entry = updates[-1]["index_entry"]
    assert entry["license"] == "mit"
    assert entry["base_model"] == ["openai-community/gpt2"]
    assert entry["datasets"] == ["wikitext", "c4"]
    assert entry["language"] == "en, fr"
    assert entry["readme_excerpt"].startswith("# Tiny model")
    assert "license:" not in entry["readme_excerpt"]
    # Token-shaped text in the card is redacted, so secret_scan does not fail the job.
    assert "hf_abcdefghij" not in entry["readme_excerpt"]
    assert entry["user_note"] == "test model"
    assert entry["readme_path"] == f"huggingface-daily/{DAY}/models__hf-internal-testing__tiny-random-gpt2/README.md"


def test_simple_yaml_fallback_matches():
    front = hf._simple_yaml(CARD.split("---")[1])
    assert hf.card_fields(front)["datasets"] == ["wikitext", "c4"]
    assert hf.card_fields(front)["language"] == "en, fr"


def test_scrub_free_text():
    text = "curl -H 'Authorization: Bearer abc' x?token=zzz ghp_ABCDEFGHIJKLMNOPQRSTUVWX"
    out = scrub_free_text(text)
    secret_scan({"readme_excerpt": out})
    assert "abc" not in out and "zzz" not in out and "ghp_ABC" not in out


# --- common contract (same as GitHub) ---------------------------------------------


def test_hf_mount_offline_defers(hf_env, archive_root):
    runner, updates, calls = hf_env
    _run(_job(), archive_root, updates, ready=(False, "NAS is not mounted"))
    assert updates[-1]["status"] == "queued"
    assert updates[-1]["error_display"] == "TNAS offline, will retry"
    assert updates[-1]["not_before"]
    assert not runner.calls and not calls
    assert not (archive_root / "huggingface-daily").exists()


def test_hf_temp_then_rename(hf_env, archive_root):
    runner, updates, calls = hf_env
    _run(_job(), archive_root, updates)
    final = archive_root / "huggingface-daily" / DAY / "models__hf-internal-testing__tiny-random-gpt2"
    assert runner.calls[0]["work_dir"].endswith(f"huggingface-daily/{DAY}/.partial-h1")
    assert (final / "snapshot" / "model.safetensors").is_file()
    assert (final / "README.md").is_file()
    assert (final / ".hub-provenance-h1.json").is_file() and (final / ".hub-tags-h1.json").is_file()
    assert not list(final.parent.glob(".partial-*"))
    last = updates[-1]
    assert last["status"] == "done" and last["download_dir"] == f"huggingface-daily/{DAY}/{final.name}"
    entry = last["index_entry"]
    assert entry["kind"] == "huggingface_repo" and entry["status"] == "archived"
    assert entry["revision_sha"] == "71034c5d8bde858ff824298bdedc65515b97d2b9"
    assert entry["file_summary"]["by_ext"][".safetensors"] == 1
    assert entry["pipeline_tag"] == "text-generation" and entry["parameter_count"] == 102714
    # Download pinned to the commit the size check saw.
    assert runner.calls[0]["spec"]["revision"] == "71034c5d8bde858ff824298bdedc65515b97d2b9"
    assert calls == [("model", "hf-internal-testing/tiny-random-gpt2", "main")]


def test_hf_idempotent(hf_env, archive_root):
    runner, updates, _ = hf_env
    _run(_job("h1"), archive_root, updates)
    _run(_job("h2"), archive_root, updates)
    assert len(runner.calls) == 1
    assert updates[-1]["status"] == "done"
    assert updates[-1]["progress"]["note"].startswith("Already archived on")
    _run(_job("h3", refresh=True), archive_root, updates)
    assert len(runner.calls) == 2


def test_hf_post_check_over_cap(hf_env, archive_root):
    runner, updates, _ = hf_env
    runner.payload_bytes = 3 * 1024 * 1024
    _run(_job(max_size_mb=1), archive_root, updates)
    assert updates[-1]["error_display"] == "Download exceeded the size limit"
    assert not list((archive_root / "huggingface-daily" / DAY).iterdir())


def test_hf_token_not_in_argv(tmp_path, monkeypatch):
    import repo_runner

    seen: dict = {}

    def fake_run(cmd, **kw):
        if cmd[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(cmd, 1, "", "")
        seen["cmd"] = cmd
        env_file = cmd[cmd.index("--env-file") + 1]
        seen["env_text"] = Path(env_file).read_text(encoding="utf-8")
        seen["timeout"] = kw.get("timeout")
        return subprocess.CompletedProcess(cmd, 0, '{"ok": true, "revision_sha": "abc"}\n', "")

    monkeypatch.setattr(repo_runner.subprocess, "run", fake_run)
    out = repo_runner.DockerRepoRunner(image="bucket-hub-repo-archiver:4").run_hf_snapshot(
        repo_id="org/name",
        spec={"repo_type": "model", "revision": "abc", "allow_patterns": None, "ignore_patterns": ["*.bin"]},
        work_dir=tmp_path / ".partial-h1",
        env={"HF_TOKEN": "hf_secretvalue1234567890abcd", "HF_HUB_DISABLE_TELEMETRY": "1"},
    )
    assert out["revision_sha"] == "abc"
    assert not any("hf_secretvalue" in part for part in seen["cmd"])
    assert "HF_TOKEN=hf_secretvalue1234567890abcd" in seen["env_text"]
    i = seen["cmd"].index("bucket-hub-repo-archiver:4")
    assert seen["cmd"][i + 1:i + 3] == ["hf_snapshot", "org/name"]
    assert json.loads(seen["cmd"][i + 3])["ignore_patterns"] == ["*.bin"]
    assert seen["timeout"] == 12 * 3600
    assert "--network=container:gluetun" in seen["cmd"]


def test_docker_runner_maps_gated_exit(tmp_path, monkeypatch):
    import repo_runner

    def fake_run(cmd, **kw):
        if cmd[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(cmd, 1, "", "")
        return subprocess.CompletedProcess(
            cmd, 3, '{"ok": false, "error_kind": "gated", "error": "401 Client Error"}\n', ""
        )

    monkeypatch.setattr(repo_runner.subprocess, "run", fake_run)
    with pytest.raises(ArchiverError) as info:
        repo_runner.DockerRepoRunner(image="x").run_hf_snapshot(
            repo_id="o/n", spec={}, work_dir=tmp_path / ".partial-h1", env={}
        )
    assert info.value.kind == "gated"


def test_partial_guard_accepts_hf_root(archive_root):
    p = hf_dated_dir(archive_root, DAY) / ".partial-h9"
    p.mkdir(parents=True)
    remove_partial_dir(p, "h9")
    assert not p.exists()
    bad = archive_root / "other" / DAY / ".partial-h9"
    bad.mkdir(parents=True)
    with pytest.raises(ValueError):
        remove_partial_dir(bad, "h9")


# --- archiver entry HF mode ------------------------------------------------------


def _entry_mod():
    path = HUB_ROOT / "docker" / "repo-archiver" / "repo_archiver_entry.py"
    spec = importlib.util.spec_from_file_location("repo_archiver_entry_hf", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_entry_hf_snapshot_args_and_card(tmp_path, monkeypatch):
    pytest.importorskip("huggingface_hub")
    import huggingface_hub

    mod = _entry_mod()
    work = tmp_path / "work"
    real_path = mod.Path
    monkeypatch.setattr(mod, "Path", lambda p: real_path(str(p).replace("/work", str(work), 1)))
    seen: dict = {}

    def fake_snapshot(**kw):
        seen.update(kw)
        d = Path(kw["local_dir"])
        d.mkdir(parents=True, exist_ok=True)
        (d / "README.md").write_text("# card\n", encoding="utf-8")
        return str(d)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot)
    monkeypatch.setenv("HF_TOKEN", "hf_tok")
    out = mod.hf_snapshot("org/name", {"repo_type": "dataset", "revision": "abc", "ignore_patterns": ["*.bin"]})
    assert out == {"ok": True, "revision_sha": "abc", "card": True}
    assert seen["repo_type"] == "dataset" and seen["revision"] == "abc"
    assert seen["ignore_patterns"] == ["*.bin"] and seen["token"] == "hf_tok"
    assert (work / "README.md").read_text(encoding="utf-8") == "# card\n"


def test_entry_hf_error_kinds():
    pytest.importorskip("huggingface_hub")
    from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

    def bare(cls, msg):
        # huggingface_hub >= 1.0 requires a ``response`` kwarg in __init__; the classifier
        # only looks at the class name, so build the instance without calling __init__.
        exc = cls.__new__(cls)
        exc.args = (msg,)
        return exc

    mod = _entry_mod()
    assert mod._hf_error_kind(bare(GatedRepoError, "gated")) == "gated"
    assert mod._hf_error_kind(bare(RepositoryNotFoundError, "nope")) == "not_found"
    assert mod._hf_error_kind(RuntimeError("disk full")) == "failed"


# --- Pi routing and worker dispatch ----------------------------------------------


H = {"x-worker-token": "test-worker"}


def test_pi_hf_url_auto_is_huggingface_repo_without_drive(hub_client):
    client, _jobs, _app = hub_client
    r = client.post("/api/jobs", json={"url": URL, "kind": "auto"})
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert job["kind"] == "huggingface_repo" and job["worker"] == "repo"
    claimed = client.post("/api/jobs/claim", headers=H, json={"lane": "repo"}).json()["job"]
    assert claimed["id"] == job["id"]


def test_pi_legacy_hf_keeps_drive_path(hub_client):
    """Legacy ``hf`` (select files) needs destination_path; it must not skip the drive check.

    Since AP-UX-1 an empty drive resolves through the ``hf_files`` preset, which
    needs TNAS › ai_language; with no drives the preset is unavailable (503).
    """
    client, jobs_dir, _app = hub_client
    (jobs_dir / "library.json").write_text('{"drives": {}}', encoding="utf-8")
    r = client.post("/api/jobs", json={"url": URL, "kind": "hf", "drive_id": "", "folder_id": ""})
    assert r.status_code == 503 and "selected files" in r.text
    r = client.post("/api/jobs", json={"url": URL, "kind": "hf", "drive_id": "nas", "folder_id": "x"})
    assert r.status_code == 400 and "Unknown drive" in r.text


def test_worker_dispatches_huggingface_repo(monkeypatch):
    import sys
    import importlib

    sys.path.insert(0, str(HUB_ROOT))
    w = importlib.reload(sys.modules["hub-worker"]) if "hub-worker" in sys.modules else importlib.import_module("hub-worker")
    seen: list[str] = []

    class NowPool:
        def submit(self, fn):
            fn()

    monkeypatch.setattr(w, "_repo_pool", lambda: NowPool())
    monkeypatch.setattr(w, "run_huggingface_repo_job", lambda job, **kw: seen.append(job["id"]))
    w._submit_repo_job({"id": "h1", "kind": "huggingface_repo", "url": URL})
    assert seen == ["h1"]
    assert "h1" not in w._repo_running
