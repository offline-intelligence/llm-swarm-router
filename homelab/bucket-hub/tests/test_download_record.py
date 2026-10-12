"""AP-5a.1 per-download record: journal merge, tombstones, notes, search, card, export, API.

Spec: ``docs/pm/2026-10/AP-5-index-architecture-v2.md`` §Per-download record (I1, I10-I13 here;
catalogue tests I2-I9 belong to AP-5a.2).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import download_record as dr
from index_writer import append_entry, build_entry
from tests.conftest import _write_job

H = {"x-worker-token": "test-worker"}
HUB_ROOT = Path(__file__).resolve().parents[1]


def _entry(eid, **kw):
    kind = kw.pop("kind", "github_repo")
    base = dict(entry_id=eid, source_id=eid, hub_job_id=kw.pop("job", eid), title=kw.pop("title", eid))
    base.update(kw)
    return build_entry(kind, **base)


@pytest.fixture()
def journal(tmp_path):
    return tmp_path / "download-index.jsonl"


# I1 merge rules
def test_i1_last_line_wins_and_events_merge(journal):
    append_entry(journal, _entry("a", title="old"))
    append_entry(journal, _entry("a", title="new"))
    append_entry(journal, dr.note_event("a", "Base model for the router"))
    append_entry(journal, _entry("b"))
    append_entry(journal, dr.tombstone("b", job_id="del1", paths=["/mnt/tnas/x"], by="storage-delete"))
    append_entry(journal, dr.tombstone("ghost"))  # unknown id: ignored
    recs = dr.load_records(journal)
    assert set(recs) == {"a", "b"}
    assert recs["a"]["title"] == "new" and recs["a"]["user_note"] == "Base model for the router"
    assert recs["b"]["status"] == "deleted" and recs["b"]["deleted_by"] == "storage-delete"
    assert recs["b"]["title"] == "b"  # data kept


def test_i1_note_is_scrubbed(journal):
    line = dr.note_event("a", "see https://x.test/?token=abc123")
    assert "abc123" not in json.dumps(line)


def test_export_cursor_returns_only_changed(journal):
    append_entry(journal, _entry("a"))
    append_entry(journal, _entry("b"))
    rows, cur = dr.export_since(journal, 0)
    assert [r["entry_id"] for r in rows] == ["a", "b"] and cur == journal.stat().st_size
    append_entry(journal, dr.note_event("a", "why"))
    rows2, cur2 = dr.export_since(journal, cur)
    assert [r["entry_id"] for r in rows2] == ["a"] and rows2[0]["user_note"] == "why"
    assert dr.export_since(journal, cur2) == ([], cur2)
    assert dr.export_since(journal, 10**9)[1] == cur2  # cursor past the end is clamped


def test_sources_excludes_failed_and_deleted(journal):
    append_entry(journal, _entry("a"))
    append_entry(journal, _entry("b", status="failed"))
    append_entry(journal, _entry("c"))
    append_entry(journal, dr.tombstone("c"))
    assert dr.sources(dr.load_records(journal)) == ["a"]


def test_search_and_terms_weights_and_deleted_filter(journal):
    append_entry(journal, _entry("n", title="nanoGPT", description="tiny llama trainer"))
    append_entry(journal, _entry("l", title="llama.cpp", description="inference"))
    append_entry(journal, _entry("d", title="llama-old"))
    append_entry(journal, dr.tombstone("d"))
    recs = dr.load_records(journal)
    res = dr.search(recs, "llama")
    assert [i["entry_id"] for i in res["items"]] == ["l", "n"]  # title (3) beats description (1.5)
    assert dr.search(recs, "llama trainer")["total"] == 1
    assert [i["entry_id"] for i in dr.search(recs, "llama", status="deleted")["items"]] == ["d"]


def test_entries_under_matches_own_folder_not_parent():
    recs = {
        "repo": {"kind": "github_repo", "rel_path": "github-daily/2026-10-12/o__r", "status": "done"},
        "file": {"kind": "http", "local_path": "/mnt/tnas/inbox", "rel_path": "x.iso", "status": "done"},
        "flat": {"kind": "magnet", "local_path": "/mnt/external/movies/torrents", "status": "done"},
    }
    root = "/mnt/tnas/repo-archive"
    assert dr.entries_under(recs, "/mnt/tnas/repo-archive/github-daily/2026-10-12", root) == ["repo"]
    assert dr.entries_under(recs, "/mnt/tnas/inbox/x.iso", root) == ["file"]
    assert dr.entries_under(recs, "/mnt/tnas/inbox/other.iso", root) == []
    assert dr.entries_under(recs, "/mnt/external/movies/torrents/Show.S01", root) == []


def test_card_has_sections_and_no_secrets():
    e = _entry("a", title="Hello-World", user_note="keep for demos", size_bytes=2048,
               readme_excerpt="Run make demo", source_url="https://github.com/o/r")
    card = dr.context_card(e)
    for h in ("## What", "## Where", "## Why", "## When", "## README excerpt"):
        assert h in card
    assert "keep for demos" in card and "2.0 KB" in card
    e["user_note"] = "Authorization: Bearer abc123xyz"
    assert "abc123xyz" not in dr.context_card(e)  # free text is scrubbed, then secret-scanned


# I12 person record on disk for folder downloads
def test_i12_provenance_writes_about_file(tmp_path):
    from repo_archive_github import write_provenance_sidecar

    e = _entry("a", title="octocat/Hello-World", user_note="first repo", size_bytes=10,
               source_url="https://github.com/octocat/Hello-World")
    write_provenance_sidecar(tmp_path, "job1", e)
    about = (tmp_path / dr.ABOUT_FILENAME).read_text(encoding="utf-8")
    assert (tmp_path / ".hub-provenance-job1.json").is_file()
    assert "octocat/Hello-World" in about and "first repo" in about and "github.com/octocat" in about


# --- Pi API -------------------------------------------------------------------


def _patch(client, jid, body):
    return client.patch(f"/api/jobs/{jid}", json=body, headers=H)


def test_api_done_job_journal_has_segment_and_preset(hub_client):
    client, jobs_dir, _ = hub_client
    _write_job(jobs_dir, {"id": "t1", "status": "running", "kind": "magnet", "title": "Show S01",
                          "preset": "tv", "segment": "tv", "destination_path": "/mnt/external/movies/torrents"})
    assert _patch(client, "t1", {"status": "done"}).status_code == 200
    rec = next(iter(dr.load_records(jobs_dir / "download-index.jsonl").values()))
    assert rec["segment"] == "tv" and rec["preset"] == "tv"


def test_i13_tv_torrent_gets_no_sidecar(hub_client, tmp_path):
    client, jobs_dir, _ = hub_client
    torrents = tmp_path / "torrents"
    torrents.mkdir()
    _write_job(jobs_dir, {"id": "t2", "status": "running", "kind": "magnet", "segment": "tv",
                          "destination_path": str(torrents)})
    _patch(client, "t2", {"status": "done"})
    assert not list(torrents.iterdir())


def test_i11_storage_delete_tombstones_and_is_not_indexed(hub_client):
    client, jobs_dir, app_mod = hub_client
    j = jobs_dir / "download-index.jsonl"
    root = app_mod.HUB_REPO_ARCHIVE_ROOT
    append_entry(j, _entry("gh", rel_path="github-daily/2026-10-12/o__r", job="g1"))
    _write_job(jobs_dir, {"id": "d1", "status": "running", "kind": "storage_delete",
                          "source_path": f"{root}/github-daily/2026-10-12/o__r"})
    _patch(client, "d1", {"status": "done"})
    recs = dr.load_records(j)
    assert set(recs) == {"gh"} and recs["gh"]["status"] == "deleted"
    assert client.get("/api/index/search", params={"q": "gh"}).json()["total"] == 0
    assert client.get("/api/index/search", params={"q": "gh", "status": "deleted"}).json()["total"] == 1


def test_purge_complete_tombstones_job_entries(hub_client):
    client, jobs_dir, _ = hub_client
    j = jobs_dir / "download-index.jsonl"
    append_entry(j, _entry("m", kind="torrent", job="p1"))
    _write_job(jobs_dir, {"id": "p1", "status": "purging", "kind": "magnet"})
    r = client.post("/api/jobs/p1/purge-complete", json={"removed_paths": ["/mnt/x/Show"]}, headers=H)
    assert r.status_code == 200
    assert dr.load_records(j)["m"]["status"] == "deleted"


def test_api_entry_card_note_export_sources(hub_client):
    client, jobs_dir, _ = hub_client
    j = jobs_dir / "download-index.jsonl"
    eid = "github_repo:octocat/Hello-World:g9"
    append_entry(j, _entry(eid, title="octocat/Hello-World"))
    assert client.get(f"/api/index/{eid}").json()["title"] == "octocat/Hello-World"
    assert client.get("/api/index/nope").status_code == 404
    card = client.get(f"/api/index/{eid}/card")
    assert card.status_code == 200 and card.text.startswith("# octocat/Hello-World")
    assert client.patch(f"/api/index/{eid}", json={"user_note": "demo"}).json()["user_note"] == "demo"
    assert client.patch(f"/api/index/{eid}", json={"user_note": "x", "title": "y"}).status_code == 422
    exp = client.get("/api/index/export")
    assert exp.headers["X-Index-Cursor"] == str(j.stat().st_size)
    assert json.loads(exp.text.splitlines()[0])["user_note"] == "demo"
    assert client.get("/api/index/export", params={"since": exp.headers["X-Index-Cursor"]}).text == ""
    assert client.get("/api/index/sources").json()["source_ids"] == [eid]


def test_api_entries_requires_worker_token(hub_client):
    client, jobs_dir, _ = hub_client
    body = {"entries": [_entry("w1")]}
    assert client.post("/api/index/entries", json=body).status_code in (401, 403)
    r = client.post("/api/index/entries", json=body, headers=H)
    assert r.status_code == 200 and r.json()["written"] == 1
    assert client.post("/api/index/entries", json={"entries": [{"entry_id": "x", "event": "deleted"}]}, headers=H).status_code == 422


# I10 back-fill
def _load_rebuild():
    spec = importlib.util.spec_from_file_location("rebuild_idx", HUB_ROOT / "scripts" / "rebuild-download-index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_i10_from_jobs_dry_run_then_write(tmp_path, capsys):
    mod = _load_rebuild()
    for job in (
        {"id": "a", "status": "done", "kind": "magnet", "title": "Show"},
        {"id": "b", "status": "done", "kind": "video", "title": "Clip"},
        {"id": "c", "status": "done", "kind": "storage_delete"},
        {"id": "d", "status": "error", "kind": "http"},
        {"id": "e", "status": "done", "kind": "http", "title": "iso"},
    ):
        _write_job(tmp_path, job)
    append_entry(tmp_path / "download-index.jsonl", _entry("pre", kind="http", job="e"))
    assert mod.main(["--from-jobs", str(tmp_path), "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["to_write"] == 2 and out["written"] == 0 and out["skipped_not_download"] == 1
    assert out["already_indexed"] == 1
    assert len(dr.load_records(tmp_path / "download-index.jsonl")) == 1
    assert mod.main(["--from-jobs", str(tmp_path)]) == 0
    recs = dr.load_records(tmp_path / "download-index.jsonl")
    assert len(recs) == 3
    segs = {r["hub_job_id"]: r.get("segment") for r in recs.values()}
    assert segs["a"] == "tv" and segs["b"] == "other"
    assert mod.main(["--from-jobs", str(tmp_path)]) == 0  # idempotent
    assert len(dr.load_records(tmp_path / "download-index.jsonl")) == 3
