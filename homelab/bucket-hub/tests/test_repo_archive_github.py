"""GitHub repo archive handler (AP-3 §T2 behaviour)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from index_writer import build_github_entry, secret_scan
from repo_archive_github import run_github_repo_job
from repo_archive_paths import final_github_dir, github_dated_dir


def test_mount_offline_defers(archive_root, fake_runner, gh_api):
    updates: list[dict] = []

    def update_job(jid, **fields):
        updates.append({"id": jid, **fields})

    run_github_repo_job(
        {"id": "j1", "url": "https://github.com/karpathy/nanoGPT", "tags": []},
        archive_root=archive_root,
        path_ready=lambda _p: (False, "NAS is not mounted"),
        update_job=update_job,
    )
    assert updates[-1]["status"] == "queued"
    assert "TNAS offline" in updates[-1]["error_display"]
    assert not fake_runner.calls


def test_idempotent_existing_final_folder(
    archive_root, fake_runner, gh_api, monkeypatch
):
    now = datetime(2026, 10, 11, 5, 0, tzinfo=timezone.utc)
    dated = github_dated_dir(archive_root, "2026-10-11")
    final = final_github_dir(dated, "karpathy/nanoGPT")
    final.mkdir(parents=True)
    updates: list[dict] = []

    def update_job(jid, **fields):
        updates.append(fields)

    run_github_repo_job(
        {
            "id": "j1",
            "url": "https://github.com/karpathy/nanoGPT",
            "tags": [],
            "options": {},
        },
        archive_root=archive_root,
        path_ready=lambda _p: (True, "nas"),
        update_job=update_job,
        now=now,
    )
    assert updates[-1]["status"] == "done"
    assert "Already archived today" in updates[-1]["progress"]["note"]
    assert not fake_runner.calls


def test_temp_then_rename(archive_root, fake_runner, gh_api):
    now = datetime(2026, 10, 11, 5, 0, tzinfo=timezone.utc)
    updates: list[dict] = []

    def update_job(jid, **fields):
        updates.append(fields)

    run_github_repo_job(
        {
            "id": "j1",
            "url": "https://github.com/karpathy/nanoGPT",
            "title": "nano",
            "tags": ["github"],
            "options": {"max_size_mb": 2048},
        },
        archive_root=archive_root,
        path_ready=lambda _p: (True, "nas"),
        update_job=update_job,
        now=now,
    )
    final = final_github_dir(github_dated_dir(archive_root, "2026-10-11"), "karpathy/nanoGPT")
    assert final.is_dir()
    assert (final / "repo.git" / "HEAD").is_file()
    assert (final / "README.md").is_file()
    assert not list(github_dated_dir(archive_root, "2026-10-11").glob(".partial-*"))
    assert updates[-1]["status"] == "done"
    assert fake_runner.calls


def test_size_cap_precheck_skips(archive_root, fake_runner, gh_api, monkeypatch):
    def big_fetch(_name):
        data = dict(gh_api)
        data["size"] = 3_000_000  # KB
        return data

    from repo_archive_github import configure

    configure(fetch_metadata=big_fetch)
    updates: list[dict] = []

    def update_job(jid, **fields):
        updates.append(fields)

    run_github_repo_job(
        {
            "id": "j1",
            "url": "https://github.com/karpathy/nanoGPT",
            "options": {"max_size_mb": 2048},
        },
        archive_root=archive_root,
        path_ready=lambda _p: (True, "nas"),
        update_job=update_job,
    )
    assert updates[-1]["status"] == "done"
    assert updates[-1]["progress"]["note"].startswith("Skipped:")
    assert not fake_runner.calls
    line = (archive_root / "download-index.jsonl").read_text(encoding="utf-8").strip()
    row = json.loads(line)
    assert row["status"] == "skipped_too_large"


def test_provenance_schema(gh_api):
    entry = build_github_entry(
        {"id": "j1", "url": "https://github.com/karpathy/nanoGPT", "tags": []},
        full_name="karpathy/nanoGPT",
        meta=gh_api,
        status="archived",
        rel_path="github-daily/2026-10-11/karpathy__nanoGPT",
        readme_excerpt="hello",
        commit_sha="abc",
        size_bytes=100,
    )
    assert entry["schema_version"] == 1
    assert entry["full_name"] == "karpathy/nanoGPT"
    assert len(entry["readme_excerpt"]) <= 2000


def test_index_secret_scan():
    from index_writer import IndexSecretError

    with pytest.raises(IndexSecretError):
        secret_scan({"readme_excerpt": "Bearer leaked"})
    with pytest.raises(IndexSecretError):
        secret_scan({"url": "http://x?apikey=abc"})


# --- AP-3.1 -------------------------------------------------------------------


def test_mount_offline_sets_backoff(archive_root, fake_runner, gh_api, monkeypatch):
    monkeypatch.setenv("HUB_REPO_DEFER_S", "90")
    now = datetime(2026, 10, 12, 1, 0, tzinfo=timezone.utc)
    updates: list[dict] = []
    run_github_repo_job(
        {"id": "j1", "url": "https://github.com/octocat/Hello-World", "tags": []},
        archive_root=archive_root,
        path_ready=lambda _p: (False, "NAS is not mounted"),
        update_job=lambda jid, **f: updates.append(f),
        now=now,
    )
    assert updates[-1]["not_before"] == "2026-10-12T01:01:30+00:00"
    assert not list(archive_root.rglob("*"))


def test_readme_fallback_when_archiver_writes_none(archive_root, gh_api, monkeypatch):
    """Old image (:1) leaves no README.md for repos whose file is plain ``README``."""
    import repo_archive_github as rag
    from repo_runner import RecordingRepoRunner

    class NoReadmeRunner(RecordingRepoRunner):
        def run_github_mirror(self, *, clone_url, work_dir, env):
            out = super().run_github_mirror(clone_url=clone_url, work_dir=work_dir, env=env)
            (work_dir / "README.md").unlink()
            return {**out, "readme_text": ""}

    monkeypatch.setattr(rag, "_fetch_readme", None)
    rag.configure(runner=NoReadmeRunner(), fetch_readme=lambda name: "Hello World!\n")
    now = datetime(2026, 10, 12, 1, 0, tzinfo=timezone.utc)
    updates: list[dict] = []
    run_github_repo_job(
        {"id": "j2", "url": "https://github.com/octocat/Hello-World", "tags": [], "options": {}},
        archive_root=archive_root,
        path_ready=lambda _p: (True, "nas"),
        update_job=lambda jid, **f: updates.append(f),
        now=now,
    )
    final = final_github_dir(github_dated_dir(archive_root, "2026-10-12"), "octocat/Hello-World")
    assert (final / "README.md").read_text(encoding="utf-8") == "Hello World!\n"
    assert updates[-1]["index_entry"]["readme_excerpt"] == "Hello World!\n"


def test_readme_fallback_failure_does_not_fail_job(archive_root, gh_api, monkeypatch):
    import repo_archive_github as rag
    from repo_runner import RecordingRepoRunner

    class NoReadmeRunner(RecordingRepoRunner):
        def run_github_mirror(self, *, clone_url, work_dir, env):
            out = super().run_github_mirror(clone_url=clone_url, work_dir=work_dir, env=env)
            (work_dir / "README.md").unlink()
            return {**out, "readme_text": ""}

    def boom(_name):
        raise RuntimeError("404")

    monkeypatch.setattr(rag, "_fetch_readme", None)
    rag.configure(runner=NoReadmeRunner(), fetch_readme=boom)
    updates: list[dict] = []
    run_github_repo_job(
        {"id": "j3", "url": "https://github.com/octocat/no-readme", "tags": [], "options": {}},
        archive_root=archive_root,
        path_ready=lambda _p: (True, "nas"),
        update_job=lambda jid, **f: updates.append(f),
        now=datetime(2026, 10, 12, 1, 0, tzinfo=timezone.utc),
    )
    assert updates[-1]["status"] == "done"
