"""AP-4.1 gated Hugging Face repos: wait for a one-click licence accept, never dead-end.

Spec: ``docs/pm/2026-10/AP-4.1-hf-gated-access.md`` (tests G1-G9).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import repo_archive_hf as hf
from index_writer import load_entries
from repo_runner import RecordingRepoRunner

FIXTURE = Path(__file__).parent / "fixtures" / "hf_model_tiny_gpt2.json"
URL = "https://huggingface.co/meta-llama/Llama-3.2-1B"
NOW = datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc)
TOKEN = "hf_fakegatetoken1234567890abcd"
H = {"x-worker-token": "test-worker"}


@pytest.fixture()
def gated_meta():
    meta = json.loads(FIXTURE.read_text(encoding="utf-8"))
    meta["gated"] = "auto"
    meta["id"] = "meta-llama/Llama-3.2-1B"
    return meta


@pytest.fixture()
def gate_env(archive_root, gated_meta, monkeypatch):
    """Fake runner, metadata and access probe; returns (runner, updates, probes, state)."""
    from repo_archive_github import configure as gh_configure

    runner = RecordingRepoRunner(payload_bytes=0)
    gh_configure(runner=runner)
    state = {"status": 403, "meta": gated_meta}
    probes: list[str] = []

    def probe(url):
        probes.append(url)
        if isinstance(state["status"], Exception):
            raise state["status"]
        return state["status"]

    hf.configure(fetch_metadata=lambda *_a: state["meta"])
    monkeypatch.setattr(hf, "_probe_access", probe)
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.delenv("HF_GATE_RECHECK_S", raising=False)
    monkeypatch.delenv("HF_GATE_SCHEDULE_S", raising=False)
    monkeypatch.delenv("HF_GATE_MAX_WAIT_H", raising=False)
    # AP-4.3 free-space guard: ample space by default so gate tests reach their own assertions.
    monkeypatch.setattr(hf, "_free_space_bytes", lambda _root: 10 * 1024 ** 4)
    return runner, [], probes, state


def _job(jid="g1", gate=None, **opts):
    job = {"id": jid, "kind": "huggingface_repo", "url": URL, "title": "llama", "tags": ["hf"], "options": opts}
    if gate is not None:
        job["gate"] = gate
    return job


def _run(job, archive_root, updates, now=NOW):
    hf.run_huggingface_repo_job(
        job,
        archive_root=archive_root,
        path_ready=lambda _p: (True, "nas"),
        update_job=lambda jid, **f: updates.append({"id": jid, **f}),
        now=now,
    )


def test_g1_not_gated_skips_probe(gate_env, archive_root):
    runner, updates, probes, state = gate_env
    state["meta"] = {**state["meta"], "gated": False}
    _run(_job(), archive_root, updates)
    assert probes == []
    assert updates[-1]["status"] == "done"
    assert updates[-1]["index_entry"]["licence_accepted_by"] is None


def test_g2_gated_without_token_waits_needs_token(gate_env, archive_root, monkeypatch):
    runner, updates, probes, _ = gate_env
    monkeypatch.delenv("HF_TOKEN")
    _run(_job(), archive_root, updates)
    last = updates[-1]
    assert last["status"] == "queued" and last["gate"]["state"] == "needs_token"
    assert last["error_display"] == hf.NEEDS_TOKEN_MSG
    assert last["not_before"] == (NOW + timedelta(seconds=60)).isoformat()  # AP-4.2 first gap
    assert probes == [] and not runner.calls


def test_g3_gated_probe_403_awaits_licence(gate_env, archive_root):
    runner, updates, probes, _ = gate_env
    _run(_job(), archive_root, updates)
    last = updates[-1]
    assert last["status"] == "queued"
    gate = last["gate"]
    assert gate["state"] == "awaiting_licence" and gate["gated"] == "auto"
    assert gate["url"] == URL and gate["since"] == NOW.isoformat() and gate["checks"] == 1
    assert "Waiting for licence: accept at " + URL == last["progress"]["note"]
    assert probes == [f"{URL}/resolve/71034c5d8bde858ff824298bdedc65515b97d2b9/README.md"]
    assert not runner.calls
    assert not list(archive_root.rglob(".partial-*"))


def test_g3_manual_gate_note(gate_env, archive_root):
    _, updates, _, state = gate_env
    state["meta"] = {**state["meta"], "gated": "manual"}
    _run(_job(), archive_root, updates)
    assert updates[-1]["gate"]["gated"] == "manual"
    assert "model owner" in updates[-1]["error_display"]


def test_g4_access_granted_downloads_and_records(gate_env, archive_root):
    runner, updates, _, state = gate_env
    since = NOW - timedelta(minutes=25)
    gate = {"state": "awaiting_licence", "gated": "auto", "url": URL, "since": since.isoformat(), "checks": 3}
    state["status"] = 302  # LFS file redirects to the CDN once access exists
    _run(_job(gate=gate), archive_root, updates)
    last = updates[-1]
    assert last["status"] == "done"
    assert "gate" in last and last["gate"] is None
    entry = last["index_entry"]
    assert entry["gated"] is True and entry["licence_accepted_by"] == "user"
    assert entry["gate_wait_s"] == 25 * 60
    assert len(runner.calls) == 1
    rows = load_entries(archive_root / "download-index.jsonl")
    assert any(r.get("licence_accepted_by") == "user" for r in rows.values())


def test_g4_counts_checks_across_claims(gate_env, archive_root):
    _, updates, _, _ = gate_env
    _run(_job(), archive_root, updates)
    first = updates[-1]["gate"]
    later = NOW + timedelta(minutes=10)
    _run(_job(gate=first), archive_root, updates, now=later)
    second = updates[-1]["gate"]
    assert second["checks"] == 2 and second["since"] == first["since"]


def test_g5_wait_expires(gate_env, archive_root):
    runner, updates, _, _ = gate_env
    since = NOW - timedelta(hours=169)
    gate = {"state": "awaiting_licence", "gated": "auto", "url": URL, "since": since.isoformat(), "checks": 1000}
    _run(_job(gate=gate), archive_root, updates)
    last = updates[-1]
    assert last["status"] == "error"
    assert last["error_display"] == "Licence not accepted within 168 h"
    assert last["gate"] is None and not runner.calls


def test_g5_wait_window_from_env(gate_env, archive_root, monkeypatch):
    _, updates, _, _ = gate_env
    monkeypatch.setenv("HF_GATE_MAX_WAIT_H", "2")
    monkeypatch.setenv("HF_GATE_RECHECK_S", "60")
    since = NOW - timedelta(hours=1)
    _run(_job(gate={"state": "awaiting_licence", "since": since.isoformat()}), archive_root, updates)
    assert updates[-1]["status"] == "queued"
    assert updates[-1]["not_before"] == (NOW + timedelta(seconds=60)).isoformat()
    _run(_job(gate={"state": "awaiting_licence", "since": (NOW - timedelta(hours=3)).isoformat()}), archive_root, updates)
    assert updates[-1]["status"] == "error"


def test_g6_gated_error_mid_download_waits_again(gate_env, archive_root):
    runner, updates, _, state = gate_env
    state["status"] = 200
    runner.raise_error = "403 Client Error: Access to model is restricted"
    runner.raise_kind = "gated"
    _run(_job(), archive_root, updates)
    last = updates[-1]
    assert last["status"] == "queued" and last["gate"]["state"] == "awaiting_licence"
    assert not list(archive_root.rglob(".partial-*"))


def test_g6_probe_error_lets_download_decide(gate_env, archive_root):
    runner, updates, _, state = gate_env
    state["status"] = RuntimeError("gluetun down")
    _run(_job(), archive_root, updates)
    assert updates[-1]["status"] == "done" and len(runner.calls) == 1


def test_probe_file_prefers_card_then_smallest():
    assert hf.probe_file({"siblings": [{"rfilename": "a.bin", "size": 9}, {"rfilename": "README.md"}]}) == "README.md"
    rows = [{"rfilename": "big.bin", "lfs": {"size": 50}}, {"rfilename": "config.json", "size": 3}]
    assert hf.probe_file({"siblings": rows}) == "config.json"
    assert hf.probe_file({"siblings": []}) is None


def test_resolve_url_dataset_and_quoting():
    url = hf.resolve_url("dataset", "org/data", "abc", "dir/a b.json")
    assert url == "https://huggingface.co/datasets/org/data/resolve/abc/dir/a%20b.json"


# --- Pi (G7) --------------------------------------------------------------------


def _queued_gate_job(client):
    job = client.post("/api/jobs", json={"url": URL, "kind": "huggingface_repo"}).json()["job"]
    claimed = client.post("/api/jobs/claim", headers=H, json={"lane": "repo"}).json()["job"]
    assert claimed["id"] == job["id"]
    gate = {"state": "awaiting_licence", "gated": "auto", "url": URL, "since": NOW.isoformat(), "checks": 1}
    later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    r = client.patch(
        f"/api/jobs/{job['id']}",
        headers=H,
        json={"status": "queued", "gate": gate, "not_before": later, "error_display": "Waiting for licence"},
    )
    assert r.status_code == 200, r.text
    return job["id"]


def test_g7_patch_stores_and_clears_gate(hub_client):
    client, _jobs, _app = hub_client
    jid = _queued_gate_job(client)
    job = client.get(f"/api/jobs/{jid}").json()
    job = job.get("job", job)
    assert job["gate"]["state"] == "awaiting_licence"
    # The claim skips it while not_before is in the future.
    assert client.post("/api/jobs/claim", headers=H, json={"lane": "repo"}).json().get("job") is None
    client.patch(f"/api/jobs/{jid}", headers=H, json={"status": "running", "gate": None})
    job = client.get(f"/api/jobs/{jid}").json()
    job = job.get("job", job)
    assert "gate" not in job


def test_g7_gate_check_clears_not_before(hub_client):
    client, _jobs, _app = hub_client
    jid = _queued_gate_job(client)
    r = client.post(f"/api/jobs/{jid}/gate-check")
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert "not_before" not in job and job["gate"]["next_check"]
    claimed = client.post("/api/jobs/claim", headers=H, json={"lane": "repo"}).json()["job"]
    assert claimed["id"] == jid


def test_g7_gate_check_404_without_gate(hub_client):
    client, _jobs, _app = hub_client
    job = client.post("/api/jobs", json={"url": URL, "kind": "huggingface_repo"}).json()["job"]
    assert client.post(f"/api/jobs/{job['id']}/gate-check").status_code == 404
    assert client.post("/api/jobs/nope/gate-check").status_code == 404


def test_g7_retry_starts_a_fresh_wait(hub_client):
    client, _jobs, _app = hub_client
    jid = _queued_gate_job(client)
    client.patch(f"/api/jobs/{jid}", headers=H, json={"status": "error", "error": "Licence not accepted within 168 h"})
    # The worker clears gate on error; simulate a stale one left behind.
    r = client.post(f"/api/jobs/{jid}/retry")
    assert r.status_code == 200, r.text
    assert "gate" not in r.json()["job"] and "not_before" not in r.json()["job"]


# --- worker (G8, G9) ------------------------------------------------------------


def _worker():
    import importlib
    import sys

    hub_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(hub_root))
    return importlib.reload(sys.modules["hub-worker"]) if "hub-worker" in sys.modules else importlib.import_module("hub-worker")


def test_g8_probe_is_head_without_redirects_token_over_stdin(monkeypatch):
    w = _worker()
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    seen = {}

    def fake_check_output(cmd, **kw):
        seen["cmd"] = cmd
        seen["input"] = kw.get("input")
        return "403"

    monkeypatch.setattr(w.subprocess, "check_output", fake_check_output)
    url = f"{URL}/resolve/abc/README.md"
    assert w.gluetun_http_status(url) == 403
    cmd = seen["cmd"]
    assert "-I" in cmd and "-L" not in cmd and "-fsSL" not in cmd
    assert cmd[-1] == url and cmd[cmd.index("-w") + 1] == "%{http_code}"
    assert TOKEN not in " ".join(cmd)  # G9: never in argv / ps
    assert seen["input"] == f"Authorization: Bearer {TOKEN}\n"


def test_g8_worker_wires_probe():
    w = _worker()
    assert hf._probe_access is w.gluetun_http_status


def test_g8_update_job_sends_gate_null(monkeypatch):
    w = _worker()
    sent = {}
    monkeypatch.setattr(w, "hub_call", lambda path, method="GET", body=None, **k: sent.update(body=body))
    w.update_job("g1", status="done", gate=None, error=None)
    assert sent["body"]["gate"] is None and sent["body"]["status"] == "done"


# --- AP-4.2 progressive re-check schedule -------------------------------------------


def test_s1_default_schedule_1_5_30_then_hourly(gate_env, archive_root):
    _, updates, _, _ = gate_env
    gaps = []
    gate, now = None, NOW
    for _ in range(6):
        _run(_job(gate=gate), archive_root, updates, now=now)
        last = updates[-1]
        nxt = datetime.fromisoformat(last["not_before"])
        assert last["gate"]["next_check"] == last["not_before"]
        gaps.append(int((nxt - now).total_seconds()))
        gate, now = last["gate"], nxt
    assert gaps == [60, 300, 1800, 3600, 3600, 3600]
    assert gate["checks"] == 6 and gate["since"] == NOW.isoformat()


def test_s2_schedule_from_env(monkeypatch):
    monkeypatch.setenv("HF_GATE_SCHEDULE_S", "120, 600,bad,5")
    monkeypatch.setenv("HF_GATE_RECHECK_S", "900")
    assert hf.gate_schedule() == (120, 600, 30)
    assert [hf.gate_recheck_seconds(n) for n in (1, 2, 3, 9)] == [120, 600, 30, 30]


def test_s2_legacy_fixed_gap(monkeypatch):
    monkeypatch.delenv("HF_GATE_SCHEDULE_S", raising=False)
    monkeypatch.setenv("HF_GATE_RECHECK_S", "600")
    assert [hf.gate_recheck_seconds(n) for n in (1, 2, 5)] == [600, 600, 600]
    monkeypatch.delenv("HF_GATE_RECHECK_S")
    assert hf.gate_schedule() == hf.DEFAULT_GATE_SCHEDULE_S


def test_s3_check_now_keeps_the_schedule_position(gate_env, archive_root):
    """A manual Check now that still fails moves on to the next gap, it does not restart."""
    _, updates, _, _ = gate_env
    gate = {"state": "awaiting_licence", "gated": "auto", "url": URL, "since": NOW.isoformat(), "checks": 2}
    _run(_job(gate=gate), archive_root, updates)
    assert updates[-1]["gate"]["checks"] == 3
    assert updates[-1]["not_before"] == (NOW + timedelta(seconds=1800)).isoformat()


def test_s4_granted_state_while_downloading(gate_env, archive_root):
    runner, updates, _, state = gate_env
    since = NOW - timedelta(minutes=7)
    gate = {"state": "awaiting_licence", "gated": "manual", "url": URL, "since": since.isoformat(), "checks": 3}
    state["status"] = 302
    _run(_job(gate=gate), archive_root, updates)
    granted = next(u for u in updates if isinstance(u.get("gate"), dict))
    g = granted["gate"]
    assert g["state"] == "granted" and g["granted_at"] == NOW.isoformat()
    assert g["checks"] == 4 and g["next_check"] is None and g["since"] == since.isoformat()
    assert granted["error_display"] is None and granted["status"] == "running"
    assert updates[-1]["status"] == "done" and updates[-1]["gate"] is None
    assert updates[-1]["index_entry"]["gate_wait_s"] == 7 * 60


def test_s4_no_granted_update_for_first_time_access(gate_env, archive_root):
    _, updates, _, state = gate_env
    state["status"] = 302
    _run(_job(), archive_root, updates)
    assert not any(isinstance(u.get("gate"), dict) for u in updates)



def test_s5_form_copy_and_waiting_filter():
    html = (Path(__file__).resolve().parents[1] / "form.html").read_text(encoding="utf-8")
    assert "function gateWaiting(j)" in html and "filter(gateWaiting)" in html
    assert "g.state === 'awaiting_licence' || g.state === 'needs_token'" in html
    assert "'Approval needed'" in html and "'Request access'" in html
    assert "Waiting for Hugging Face access (" in html
    assert "Next automatic check in" in html
