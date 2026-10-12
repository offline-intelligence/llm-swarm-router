"""AP-3.1: lane-aware claim, TNAS back-off and worker PATCH fields."""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.conftest import _write_job

HUB_ROOT = Path(__file__).resolve().parents[1]
H = {"x-worker-token": "test-worker"}


def _worker_mod():
    sys.path.insert(0, str(HUB_ROOT))
    if "hub-worker" in sys.modules:
        return importlib.reload(sys.modules["hub-worker"])
    return importlib.import_module("hub-worker")


def _iso(delta_s: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_s)).isoformat()


# --- Pi claim -----------------------------------------------------------------


def test_aria2_lane_skips_repo_job_queued_ahead(hub_client):
    """The starvation case: repo job sorted first must not reach the aria2 loop."""
    client, jobs_dir, _app = hub_client
    _write_job(jobs_dir, {"id": "r1", "status": "queued", "kind": "github_repo", "queue_rank": 1})
    _write_job(jobs_dir, {"id": "m1", "status": "queued", "kind": "magnet", "queue_rank": 2})
    r = client.post("/api/jobs/claim", headers=H, json={"lane": "aria2"})
    assert r.json()["job"]["id"] == "m1"


def test_aria2_lane_skips_repo_while_clone_running(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(jobs_dir, {"id": "r0", "status": "running", "kind": "github_repo", "queue_rank": 0})
    _write_job(jobs_dir, {"id": "r1", "status": "queued", "kind": "github_repo", "queue_rank": 1})
    _write_job(jobs_dir, {"id": "r2", "status": "queued", "kind": "github_repo", "queue_rank": 2})
    _write_job(jobs_dir, {"id": "m1", "status": "queued", "kind": "magnet", "queue_rank": 3})
    r = client.post("/api/jobs/claim", headers=H, json={"lane": "aria2"})
    assert r.json()["job"]["id"] == "m1"


def test_repo_lane_skips_torrent_queued_ahead(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(jobs_dir, {"id": "m1", "status": "queued", "kind": "magnet", "queue_rank": 1})
    _write_job(jobs_dir, {"id": "r1", "status": "queued", "kind": "github_repo", "queue_rank": 2})
    r = client.post("/api/jobs/claim", headers=H, json={"lane": "repo"})
    assert r.json()["job"]["id"] == "r1"


def test_lane_with_nothing_eligible_returns_none(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(jobs_dir, {"id": "m1", "status": "queued", "kind": "magnet", "queue_rank": 1})
    r = client.post("/api/jobs/claim", headers=H, json={"lane": "repo"})
    assert r.json()["job"] is None
    assert client.get("/api/jobs/m1").json()["status"] == "queued"


def test_repo_meta_lane(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(jobs_dir, {"id": "r1", "status": "queued", "kind": "github_repo", "queue_rank": 1})
    _write_job(jobs_dir, {"id": "s1", "status": "queued", "kind": "github_stars_sync", "queue_rank": 2})
    r = client.post("/api/jobs/claim", headers=H, json={"lane": "repo_meta"})
    assert r.json()["job"]["id"] == "s1"


def test_no_body_keeps_legacy_any_lane_claim(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(jobs_dir, {"id": "r1", "status": "queued", "kind": "github_repo", "queue_rank": 1})
    _write_job(jobs_dir, {"id": "m1", "status": "queued", "kind": "magnet", "queue_rank": 2})
    assert client.post("/api/jobs/claim", headers=H).json()["job"]["id"] == "r1"


def test_empty_body_keeps_legacy_any_lane_claim(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(jobs_dir, {"id": "m1", "status": "queued", "kind": "magnet", "queue_rank": 1})
    assert client.post("/api/jobs/claim", headers=H, json={}).json()["job"]["id"] == "m1"


def test_unknown_lane_rejected(hub_client):
    client, _jobs_dir, _app = hub_client
    r = client.post("/api/jobs/claim", headers=H, json={"lane": "bogus"})
    assert r.status_code == 400


def test_not_before_in_future_is_skipped(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(
        jobs_dir,
        {"id": "r1", "status": "queued", "kind": "github_repo", "queue_rank": 1, "not_before": _iso(300)},
    )
    _write_job(jobs_dir, {"id": "m1", "status": "queued", "kind": "magnet", "queue_rank": 2})
    assert client.post("/api/jobs/claim", headers=H, json={"lane": "repo"}).json()["job"] is None
    assert client.post("/api/jobs/claim", headers=H).json()["job"]["id"] == "m1"


def test_not_before_in_past_is_claimable(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(
        jobs_dir,
        {"id": "r1", "status": "queued", "kind": "github_repo", "queue_rank": 1, "not_before": _iso(-5)},
    )
    assert client.post("/api/jobs/claim", headers=H, json={"lane": "repo"}).json()["job"]["id"] == "r1"


# --- Pi PATCH fields --------------------------------------------------------------


def test_patch_stores_error_display_resolved_not_before(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(jobs_dir, {"id": "r1", "status": "claimed", "kind": "github_repo"})
    when = _iso(120)
    r = client.patch(
        "/api/jobs/r1",
        headers=H,
        json={
            "status": "queued",
            "error_display": "TNAS offline, will retry",
            "not_before": when,
            "resolved": {"full_name": "octocat/Hello-World"},
        },
    )
    assert r.status_code == 200
    job = client.get("/api/jobs/r1").json()
    assert job["error_display"] == "TNAS offline, will retry"
    assert job["not_before"] == when
    assert job["resolved"]["full_name"] == "octocat/Hello-World"


def test_running_clears_error_display_and_not_before(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(
        jobs_dir,
        {
            "id": "r1",
            "status": "claimed",
            "kind": "github_repo",
            "error_display": "TNAS offline, will retry",
            "not_before": _iso(-1),
        },
    )
    client.patch("/api/jobs/r1", headers=H, json={"status": "running"})
    job = client.get("/api/jobs/r1").json()
    assert job["error_display"] is None
    assert "not_before" not in job


def test_raw_error_still_wins_over_stored_display(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(jobs_dir, {"id": "r1", "status": "running", "kind": "github_repo"})
    client.patch(
        "/api/jobs/r1",
        headers=H,
        json={"status": "error", "error": "Repository not found or private", "error_display": "x"},
    )
    assert client.get("/api/jobs/r1").json()["error_display"] == "Repository not found or private"


# --- Worker -----------------------------------------------------------------------


def test_claim_next_sends_lane(monkeypatch):
    mod = _worker_mod()
    calls: list[dict] = []

    def fake_hub_call(path, method="GET", body=None):
        calls.append({"path": path, "method": method, "body": body})
        return {"job": None}

    monkeypatch.setattr(mod, "hub_call", fake_hub_call)
    mod.claim_next("aria2")
    mod.claim_next()
    assert calls[0] == {"path": "/api/jobs/claim", "method": "POST", "body": {"lane": "aria2"}}
    assert calls[1]["body"] == {}


def test_main_loop_claims_pass_lanes():
    """Every dispatch section in the main loop names its lane (guards a regression)."""
    src = (HUB_ROOT / "hub-worker.py").read_text(encoding="utf-8")
    for lane in ("aria2", "video", "repo", "repo_meta"):
        assert f'claim_next("{lane}")' in src


def test_gluetun_token_not_in_argv(monkeypatch):
    mod = _worker_mod()
    monkeypatch.setenv("HUB_GITHUB_TOKEN", "ghp_secretvalue123")
    seen: dict = {}

    def fake_check_output(cmd, text=True, timeout=None, input=None):
        seen["cmd"] = cmd
        seen["input"] = input
        return '{"ok": true}'

    monkeypatch.setattr(mod.subprocess, "check_output", fake_check_output)
    assert mod.gluetun_http_json("https://api.github.com/repos/octocat/Hello-World") == {"ok": True}
    assert not any("ghp_secretvalue123" in part for part in seen["cmd"])
    assert "-i" in seen["cmd"]
    assert seen["cmd"][-3:-1] == ["-H", "@-"]
    assert "--network" in seen["cmd"] and "container:gluetun" in seen["cmd"]
    assert seen["input"] == "Authorization: Bearer ghp_secretvalue123\n"


def test_gluetun_no_token_no_stdin(monkeypatch):
    mod = _worker_mod()
    monkeypatch.delenv("HUB_GITHUB_TOKEN", raising=False)
    seen: dict = {}

    def fake_check_output(cmd, text=True, timeout=None, input=None):
        seen["cmd"] = cmd
        seen["input"] = input
        return "{}"

    monkeypatch.setattr(mod.subprocess, "check_output", fake_check_output)
    mod.gluetun_http_json("https://api.github.com/repos/octocat/Hello-World")
    assert "-i" not in seen["cmd"] and "@-" not in seen["cmd"]
    assert seen["input"] is None


def test_github_readme_fetch_decodes_base64(monkeypatch):
    import base64

    mod = _worker_mod()
    payload = {"encoding": "base64", "content": base64.b64encode(b"Hello World!\n").decode()}
    monkeypatch.setattr(mod, "gluetun_http_json", lambda url, timeout=25: payload)
    assert mod._github_readme_fetch("octocat/Hello-World") == "Hello World!\n"
