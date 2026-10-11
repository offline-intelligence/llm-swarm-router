"""Repo lane claim separation (AP-3 §T1)."""
from __future__ import annotations

from tests.conftest import _write_job


def test_repo_job_claimable_while_aria2_running(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(
        jobs_dir,
        {"id": "m1", "status": "running", "kind": "magnet", "queue_rank": 1},
    )
    _write_job(
        jobs_dir,
        {
            "id": "r1",
            "status": "queued",
            "kind": "github_repo",
            "url": "https://github.com/octocat/Hello-World",
            "queue_rank": 2,
        },
    )
    r = client.post("/api/jobs/claim", headers={"x-worker-token": "test-worker"})
    assert r.json()["job"]["id"] == "r1"


def test_aria2_claimable_while_repo_running(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(
        jobs_dir,
        {
            "id": "r1",
            "status": "running",
            "kind": "github_repo",
            "queue_rank": 1,
        },
    )
    _write_job(
        jobs_dir,
        {"id": "m1", "status": "queued", "kind": "magnet", "queue_rank": 2},
    )
    r = client.post("/api/jobs/claim", headers={"x-worker-token": "test-worker"})
    assert r.json()["job"]["id"] == "m1"


def test_repo_slot_limit(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(
        jobs_dir,
        {"id": "r1", "status": "running", "kind": "github_repo", "queue_rank": 1},
    )
    _write_job(
        jobs_dir,
        {"id": "r2", "status": "queued", "kind": "github_repo", "queue_rank": 2},
    )
    r = client.post("/api/jobs/claim", headers={"x-worker-token": "test-worker"})
    assert r.json().get("job") is None


def test_repo_meta_not_blocked_by_repo(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(
        jobs_dir,
        {"id": "r1", "status": "running", "kind": "github_repo", "queue_rank": 1},
    )
    _write_job(
        jobs_dir,
        {
            "id": "s1",
            "status": "queued",
            "kind": "github_stars_sync",
            "queue_rank": 2,
        },
    )
    r = client.post("/api/jobs/claim", headers={"x-worker-token": "test-worker"})
    assert r.json()["job"]["id"] == "s1"


def test_exclusive_blocks_repo(hub_client):
    client, jobs_dir, _app = hub_client
    _write_job(
        jobs_dir,
        {"id": "x1", "status": "running", "kind": "sync", "queue_rank": 1},
    )
    _write_job(
        jobs_dir,
        {"id": "r1", "status": "queued", "kind": "github_repo", "queue_rank": 2},
    )
    r = client.post("/api/jobs/claim", headers={"x-worker-token": "test-worker"})
    assert r.json().get("job") is None


def test_legacy_github_hf_in_repo_bucket(hub_client):
    client, jobs_dir, app_mod = hub_client
    for kind in ("github", "hf"):
        _write_job(
            jobs_dir,
            {"id": kind, "status": "running", "kind": kind, "queue_rank": 1},
        )
        assert app_mod._job_kind_bucket({"kind": kind}) == "repo"


def test_repo_kinds_never_aria2():
    from job_kinds import dispatch_route, is_aria2_job

    kinds = (
        "github_repo",
        "huggingface_repo",
        "github_release",
        "github_stars_sync",
    )
    for kind in kinds:
        job = {"kind": kind, "worker": "repo"}
        assert is_aria2_job(job) is False
        assert dispatch_route(job) in ("repo", "repo_meta")


def test_create_job_ignores_drive_for_repo_kinds(hub_client):
    client, _jobs_dir, _app = hub_client
    r = client.post(
        "/api/jobs",
        json={
            "kind": "github_repo",
            "url": "https://github.com/octocat/Hello-World",
            "title": "octocat/Hello-World",
            "options": {"max_size_mb": 100},
            "tags": ["github"],
        },
    )
    assert r.status_code == 200
    job = r.json()["job"]
    assert job["kind"] == "github_repo"
    assert job["options"]["max_size_mb"] == 100


def test_repo_lane_api(hub_client):
    client, _jobs_dir, _app = hub_client
    r = client.get("/api/repo-lane")
    assert r.status_code == 200
    body = r.json()
    assert "slot_repo" in body
    assert body["active_repo"] == 0
