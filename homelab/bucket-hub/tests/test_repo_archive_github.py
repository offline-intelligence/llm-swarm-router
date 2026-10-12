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
