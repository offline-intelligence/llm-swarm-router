"""Shared Hub API test fixtures."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HUB_ROOT = Path(__file__).resolve().parents[1]


def _write_job(jobs_dir: Path, job: dict) -> None:
    sub = jobs_dir / "jobs"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / f"{job['id']}.json").write_text(json.dumps(job), encoding="utf-8")


@pytest.fixture()
def hub_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBS_DIR", str(tmp_path))
    monkeypatch.setenv("HUB_WORKER_TOKEN", "test-worker")
    monkeypatch.setenv("HUB_MAX_CONCURRENT_ARIA2", "2")
    monkeypatch.setenv("HUB_SLOT_VIDEO", "1")
    monkeypatch.setenv("HUB_SLOT_ARCHIVE", "0")
    monkeypatch.setenv("HUB_SLOT_REPO", "1")
    monkeypatch.setenv("HUB_SLOT_REPO_META", "1")
    (tmp_path / "jobs").mkdir()
    (tmp_path / "library.json").write_text('{"drives":[]}', encoding="utf-8")
    sys.path.insert(0, str(HUB_ROOT))
    if "app" in sys.modules:
        app_mod = importlib.reload(sys.modules["app"])
    else:
        app_mod = importlib.import_module("app")
    return TestClient(app_mod.app), tmp_path, app_mod


@pytest.fixture()
def archive_root(tmp_path, monkeypatch):
    root = tmp_path / "tnas" / "repo-archive"
    root.mkdir(parents=True)
    monkeypatch.setenv("HUB_REPO_ARCHIVE_ROOT", str(root))
    return root


@pytest.fixture()
def fake_runner():
    from repo_runner import RecordingRepoRunner

    runner = RecordingRepoRunner()
    from repo_archive_github import configure

    configure(runner=runner)
    return runner


@pytest.fixture()
def gh_api(monkeypatch):
    import json
    from pathlib import Path

    from repo_archive_github import configure

    fixture = Path(__file__).parent / "fixtures" / "github_repo_nanogpt.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))

    def fetch(full_name: str):
        return {**data, "full_name": full_name}

    configure(fetch_metadata=fetch)
    return data
