"""AP-5a.2: the ai-server download catalogue (hub_index.py) and its Pi / worker / overnight hooks."""
from __future__ import annotations

import gzip
import importlib
import importlib.util
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import download_record
import hub_index
from hub_index import Catalogue, Root, WalkStats, fs_group, fts_query, walk_tree

HUB_ROOT = Path(__file__).resolve().parents[1]
TOKEN = "worker-token-for-tests"


def _touch(path: Path, size: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


@pytest.fixture
def tree(tmp_path):
    ext = tmp_path / "ext"
    tnas = tmp_path / "tnas"
    _touch(ext / "tv/The Office/Season 3/The.Office.S03E01.mkv", 100)
    _touch(ext / "tv/The Office/Season 3/The.Office.S03E02.mkv", 120)
    _touch(ext / "tv/The Office/.hub-tags-j9.json")
    _touch(ext / "torrents/Heat.1995.1080p/Heat.1995.mkv", 300)
    _touch(ext / "movies/Heat (1995)/Heat (1995).mkv", 300)
    _touch(ext / "loose-notes.txt")
    _touch(ext / "@eaDir/thumb.jpg")
    _touch(ext / "torrents/.partial-abc/part.bin")
    gh = tnas / "repo-archive/github-daily/2026-10-12/octocat__Hello-World"
    _touch(gh / "repo.git/HEAD")
    _touch(gh / "repo.git/objects/pack/p.pack", 50)
    _touch(gh / "ABOUT-THIS-DOWNLOAD.md")
    _touch(gh / ".hub-provenance-j1.json")
    hf = tnas / "repo-archive/huggingface-daily/2026-10-12/google__gemma"
    _touch(hf / "snapshot/model.safetensors", 500)
    _touch(hf / "snapshot/.cache/huggingface/lock")
    roots = [Root("ext_movies", str(ext), "Expansion HDD"), Root("tnas", str(tnas), "TNAS")]
    return tmp_path, roots


def _cat(tmp_path, roots, mounted=None, walker=None):
    kw = {}
    if walker is not None:
        kw["walker"] = walker
    state = {"up": True} if mounted is None else mounted
    cat = Catalogue(
        tmp_path / "db/catalog.sqlite",
        roots=roots,
        archive_root=str(tmp_path / "tnas/repo-archive"),
        mounted=lambda p: state["up"] if isinstance(state, dict) else state(p),
        **kw,
    )
    return cat, state


GH_RECORD = {
    "entry_id": "github_repo:octocat/Hello-World",
    "kind": "github_repo",
    "title": "octocat/Hello-World",
    "full_name": "octocat/Hello-World",
    "rel_path": "github-daily/2026-10-12/octocat__Hello-World",
    "hub_job_id": "j1",
    "user_note": "classic sample repo for smoke tests",
    "readme_excerpt": "My first repository on GitHub",
    "size_bytes": 12345,
    "status": "done",
}


def _scan_all(cat, roots):
    return [cat.scan_root(r) for r in roots]


def test_i2_grouping_and_skips(tree):
    tmp_path, roots = tree
    cat, _ = _cat(tmp_path, roots)
    cat.ingest_records([GH_RECORD])
    _scan_all(cat, roots)
    items = {r["item_id"]: r for r in cat.db.execute("SELECT * FROM items")}
    assert items["fs:ext_movies:tv/The Office"]["kind"] == "tv"
    assert items["fs:ext_movies:tv/The Office"]["file_count"] == 2
    assert items["fs:ext_movies:torrents/Heat.1995.1080p"]["kind"] == "torrent"
    assert items["fs:ext_movies:movies/Heat (1995)"]["kind"] == "movie"
    assert items["fs:ext_movies:loose-notes.txt"]["kind"] == "file"
    hf = items["fs:tnas:repo-archive/huggingface-daily/2026-10-12/google__gemma"]
    assert (hf["kind"], hf["title"], hf["file_count"]) == ("huggingface_repo", "google/gemma", 1)
    gh = items[GH_RECORD["entry_id"]]
    assert (gh["source"], gh["status"], gh["root_id"]) == ("hub", "present", "tnas")
    names = {r["rel_path"] for r in cat.db.execute("SELECT rel_path FROM files")}
    gh_rel = "repo-archive/github-daily/2026-10-12/octocat__Hello-World"
    assert f"{gh_rel}/repo.git" in names  # one opaque entry for the bare mirror
    assert not any("/repo.git/" in n for n in names)
    assert not any(s in n for n in names for s in ("@eaDir", ".partial-", ".cache", ".hub-"))
    owned = {r["rel_path"] for r in cat.db.execute("SELECT rel_path FROM files WHERE item_id=?", (GH_RECORD["entry_id"],))}
    assert owned == {f"{gh_rel}/repo.git", f"{gh_rel}/ABOUT-THIS-DOWNLOAD.md"}
    assert gh["size_bytes"] == 12345  # the journal size beats the files sum when repo.git is opaque


def test_fs_group_rules():
    assert fs_group("tv/Show/Season 1/e1.mkv") == ("tv/Show", "tv")
    assert fs_group("repo-archive/github-daily/releases/o__r/v1.2/source.tar.gz") == (
        "repo-archive/github-daily/releases/o__r/v1.2",
        "github_repo",
    )
    assert fs_group("website_backups/example.com/index.html") == ("website_backups/example.com", "website_archive")
    assert fs_group("a.iso") == ("a.iso", "file")


def test_i3_missing_offline_and_back(tree):
    tmp_path, roots = tree
    cat, state = _cat(tmp_path, roots)
    _scan_all(cat, roots)
    ep2 = tmp_path / "ext/tv/The Office/Season 3/The.Office.S03E02.mkv"
    ep2.unlink()
    c = cat.scan_root(roots[0])
    assert c["missing"] == 1
    st = dict(cat.db.execute("SELECT rel_path, status FROM files WHERE root_id='ext_movies'").fetchall())
    assert st["tv/The Office/Season 3/The.Office.S03E02.mkv"] == "missing"
    assert st["tv/The Office/Season 3/The.Office.S03E01.mkv"] == "present"
    state["up"] = False
    c = cat.scan_root(roots[0])
    assert c["mounted"] is False
    st = dict(cat.db.execute("SELECT rel_path, status FROM files WHERE root_id='ext_movies'").fetchall())
    assert st["tv/The Office/Season 3/The.Office.S03E01.mkv"] == "offline"
    assert st["tv/The Office/Season 3/The.Office.S03E02.mkv"] == "missing"  # rows kept, nothing purged
    hit = cat.search("office")["items"][0]
    assert hit["status"] == "offline" and hit["where"].endswith("(offline)")
    state["up"] = True
    cat.scan_root(roots[0])
    st = dict(cat.db.execute("SELECT rel_path, status FROM files WHERE root_id='ext_movies'").fetchall())
    assert st["tv/The Office/Season 3/The.Office.S03E01.mkv"] == "present"


def test_i3b_empty_listing_of_big_root_is_not_a_mass_delete(tmp_path):
    root = tmp_path / "big"
    for i in range(120):
        _touch(root / f"d{i % 3}/f{i}.bin")
    r = Root("tnas", str(root), "TNAS")
    cat, _ = _cat(tmp_path, [r])
    cat.scan_root(r)
    empty = lambda root_path, prefix, prev, timeout: ([{"d": "", "m": 1, "n": 2, "subdirs": [], "files": []}], True)  # noqa: E731
    cat.walker = empty
    c = cat.scan_root(r)
    assert c.get("suspect_empty") and c["missing"] == 0
    assert cat.db.execute("SELECT COUNT(*) FROM files WHERE status='missing'").fetchone()[0] == 0


def test_incomplete_walk_marks_nothing_missing(tree):
    tmp_path, roots = tree
    cat, _ = _cat(tmp_path, roots)
    _scan_all(cat, roots)
    cat.walker = lambda root_path, prefix, prev, timeout: ([], False)  # timed out / child died
    assert cat.scan_root(roots[0])["missing"] == 0


def _prev_from(events):
    return {e["d"]: [e["m"], e["n"], e["subdirs"]] for e in events if "m" in e}


def test_i4_incremental_stats_only_changed_folders(tree):
    tmp_path, _roots = tree
    root = str(tmp_path / "ext")
    s1 = WalkStats()
    ev1 = list(walk_tree(root, "", {}, s1))
    dirs = len(ev1)
    s2 = WalkStats()
    ev2 = list(walk_tree(root, "", _prev_from(ev1), s2))
    assert all(e.get("same") for e in ev2)
    assert s2.stat_calls == dirs  # one stat per folder, no file stats
    time.sleep(0.01)
    _touch(tmp_path / "ext/tv/The Office/Season 3/The.Office.S03E03.mkv")
    s3 = WalkStats()
    ev3 = list(walk_tree(root, "", _prev_from(ev1), s3))
    changed = [e for e in ev3 if not e.get("same")]
    assert [e["d"] for e in changed] == ["tv/The Office/Season 3"]
    assert s3.stat_calls == dirs + 3  # the three episodes in the changed folder
    assert s1.stat_calls > s3.stat_calls


def test_i4_catalogue_reuses_unchanged_folders(tree):
    tmp_path, roots = tree
    cat, _ = _cat(tmp_path, roots)
    first = cat.scan_root(roots[0])
    second = cat.scan_root(roots[0])
    assert second["same_dirs"] == second["dirs"] == first["dirs"]
    assert (second["new"], second["changed"], second["missing"]) == (0, 0, 0)


def test_subprocess_walker_matches_in_process(tree):
    tmp_path, _roots = tree
    root = str(tmp_path / "tnas")
    events, complete = hub_index.subprocess_walker(root, "", {}, 60)
    assert complete
    assert events == list(walk_tree(root, "", {}))


def test_i5_fts_and_semantics_ranking_and_file_hits(tree):
    tmp_path, roots = tree
    cat, _ = _cat(tmp_path, roots)
    other = dict(GH_RECORD, entry_id="github_repo:x/y", full_name="x/y", title="x/y",
                 rel_path="github-daily/2026-10-12/x__y", user_note="", readme_excerpt="fork of octocat sample")
    cat.ingest_records([GH_RECORD, other])
    _scan_all(cat, roots)
    assert cat.search("office")["items"][0]["item_id"] == "fs:ext_movies:tv/The Office"
    assert cat.search("hello world")["items"][0]["item_id"] == GH_RECORD["entry_id"]
    assert cat.search("hello zebra")["total"] == 0  # every term must match
    res = cat.search("octocat")["items"]
    assert [r["item_id"] for r in res[:2]] == [GH_RECORD["entry_id"], "github_repo:x/y"]  # title beats excerpt
    assert cat.search("smoke tests")["items"][0]["item_id"] == GH_RECORD["entry_id"]  # user_note
    files = cat.search("S03E01", scope="files")["files"]
    assert files[0]["item"]["item_id"] == "fs:ext_movies:tv/The Office"
    assert files[0]["where"] == "Expansion HDD › tv › The Office/Season 3/The.Office.S03E01.mkv"
    gh = cat.search("hello", kind="github_repo")["items"][0]
    assert gh["where"] == "TNAS › repo-archive › github-daily/2026-10-12/octocat__Hello-World"
    assert cat.search('" OR * NEAR(', scope="all")["total"] == 0  # FTS syntax never reaches SQLite
    assert fts_query('a "b"') == '"a"* "b"*'


def test_i11_tombstone_marks_item_and_files_deleted(tree):
    tmp_path, roots = tree
    cat, _ = _cat(tmp_path, roots)
    cat.ingest_records([GH_RECORD])
    _scan_all(cat, roots)
    c = cat.ingest_records([dict(GH_RECORD, status="deleted", deleted_at="2026-10-12T10:00:00+00:00")])
    assert c["deleted"] == 1
    assert cat.search("hello")["total"] == 0
    assert cat.search("hello", status="deleted")["items"][0]["status"] == "deleted"
    st = {r["status"] for r in cat.db.execute("SELECT status FROM files WHERE item_id=?", (GH_RECORD["entry_id"],))}
    assert st == {"deleted"}
    cat.scan_root(roots[1])  # files still on disk in this test: stay deleted until re-downloaded
    gh = cat.db.execute("SELECT status FROM items WHERE item_id=?", (GH_RECORD["entry_id"],)).fetchone()
    assert gh["status"] == "deleted"


def test_purge_after_30_days(tree):
    tmp_path, roots = tree
    cat, _ = _cat(tmp_path, roots)
    cat.ingest_records([GH_RECORD])
    _scan_all(cat, roots)
    cat.ingest_records([dict(GH_RECORD, status="deleted", deleted_at="2026-08-01T00:00:00+00:00")])
    (tmp_path / "ext/loose-notes.txt").unlink()
    cat.scan_root(roots[0])
    cat.db.execute("UPDATE files SET missing_since='2026-08-01T00:00:00+00:00' WHERE status='missing'")
    cat.db.commit()
    out = cat.purge()
    assert out["items"] == 1 and out["files"] >= 1
    assert cat.db.execute("SELECT COUNT(*) FROM items WHERE item_id=?", (GH_RECORD["entry_id"],)).fetchone()[0] == 0


def test_journal_tail_cursor_and_reset(tree):
    tmp_path, roots = tree
    cat, _ = _cat(tmp_path, roots)
    calls = []

    def fetch(since):
        calls.append(since)
        return ([GH_RECORD], 500) if since == 0 else ([], 500)

    assert cat.tail_journal(fetch)["new"] == 1
    assert cat.tail_journal(fetch)["records"] == 0
    assert calls == [0, 500]
    cat.set_meta("journal_cursor", 900)  # journal replaced by a shorter file
    cat.tail_journal(fetch)
    assert calls[-2:] == [900, 0] and cat.meta("journal_cursor") == "500"


class _FakePi(BaseHTTPRequestHandler):
    snapshot: bytes = b""
    rows: list = []

    def do_GET(self):  # noqa: N802
        body = "".join(json.dumps(r) + "\n" for r in self.rows).encode()
        self.send_response(200)
        self.send_header("X-Index-Cursor", "77")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):  # noqa: N802
        n = int(self.headers["Content-Length"])
        type(self).snapshot = self.rfile.read(n)
        ok = self.headers.get("X-Worker-Token") == TOKEN
        body = json.dumps({"ok": ok, "items": 3, "bytes": n}).encode()
        self.send_response(200 if ok else 401)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_pi_fetch_falls_back_across_hub_urls(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _FakePi)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _FakePi.rows = [GH_RECORD]
    dead = "http://127.0.0.1:9"
    monkeypatch.setenv("HUB_URL", f"{dead},http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setenv("HUB_WORKER_TOKEN", TOKEN)
    rows, cursor = hub_index.pi_fetch(0, timeout=3)
    assert (rows[0]["entry_id"], cursor) == (GH_RECORD["entry_id"], 77)
    out = hub_index.pi_push_snapshot(gzip.compress(b'{"entry_id":"a"}\n'), timeout=3)
    assert out["pushed"] and _FakePi.snapshot
    srv.shutdown()


@pytest.fixture
def service(tree):
    tmp_path, roots = tree
    cat, _ = _cat(tmp_path, roots)
    svc = hub_index.Service(cat, TOKEN, fetch=lambda since: ([GH_RECORD], 10), push=lambda data: {"pushed": True, "bytes": len(data)})
    srv = hub_index.ThreadingHTTPServer(("127.0.0.1", 0), hub_index.make_handler(svc))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield svc, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _post(url, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Worker-Token"] = token
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read())


def test_i6_token_required_and_no_secrets_in_output(service):
    svc, base = service
    assert _post(f"{base}/ingest", {"job_id": "j1"})[0] == 401
    assert _post(f"{base}/ingest", {"job_id": "j1"}, "wrong")[0] == 401
    assert _post(f"{base}/rebuild", {}, "wrong")[0] == 401
    assert _post(f"{base}/ingest", {"job_id": "j1"}, TOKEN)[0] == 202
    leaky = dict(GH_RECORD, entry_id="leaky", full_name="leaky/repo", rel_path="", kind="http",
                 user_note="paste ghp_" + "a" * 36)
    svc.cat.ingest_records([leaky])
    assert svc.cat.search("leaky")["total"] == 1  # counted, but the row itself is withheld
    assert svc.cat.search("leaky")["items"] == []
    assert "ghp_" not in json.dumps(_get(f"{base}/search?q=leaky"))


def test_service_rebuild_health_item_and_nudge(service):
    svc, base = service
    code, out = _post(f"{base}/rebuild", {"timeout_s": 60}, TOKEN)
    assert code == 200 and out["ok"] and out["items"] >= 6 and out["snapshot"]["pushed"]
    assert {k: out[k] for k in ("new", "missing")} == {"new": out["new"], "missing": 0} and out["new"] > 0
    h = _get(f"{base}/health")
    assert h["schema_version"] == 1 and {r["root_id"] for r in h["roots"]} == {"ext_movies", "tnas"}
    assert all(r["mounted"] and r["last_full_scan"] for r in h["roots"])
    item = _get(f"{base}/item/" + urllib.request.quote(GH_RECORD["entry_id"], safe=""))
    assert item["record"]["user_note"] == GH_RECORD["user_note"] and len(item["files"]) == 2
    # a nudge for job j1 scans only that job's folder
    _touch(Path(svc.cat.archive_root) / GH_RECORD["rel_path"] / "CHANGELOG-zebra.txt")
    out = svc.handle_nudge({"job_id": "j1"})
    assert len(out["scans"]) == 1 and out["scans"][0]["new"] == 1
    assert svc.cat.search("zebra", scope="files")["files"][0]["item"]["item_id"] == GH_RECORD["entry_id"]


def test_i8_snapshot_round_trip_through_the_pi(tree, tmp_path, monkeypatch):
    tmp, roots = tree
    cat, _ = _cat(tmp, roots)
    cat.ingest_records([GH_RECORD])
    _scan_all(cat, roots)
    data = cat.snapshot_bytes()
    monkeypatch.setenv("JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("HUB_WORKER_TOKEN", TOKEN)
    (tmp_path / "jobs").mkdir()
    sys.path.insert(0, str(HUB_ROOT))
    import app as app_mod

    app_mod = importlib.reload(app_mod)
    from fastapi.testclient import TestClient

    client = TestClient(app_mod.app)
    assert client.put("/api/index/snapshot", content=data).status_code == 401
    r = client.put("/api/index/snapshot", content=data, headers={"X-Worker-Token": TOKEN})
    assert r.status_code == 200 and r.json()["items"] == cat.totals()[0]
    bad = client.put("/api/index/snapshot", content=b"not gzip", headers={"X-Worker-Token": TOKEN})
    assert bad.status_code == 422
    records = download_record.load_snapshot(tmp_path / "jobs/index-snapshot.jsonl.gz")
    hits = download_record.search(records, "classic sample")["items"]
    assert hits[0]["entry_id"] == GH_RECORD["entry_id"]
    assert hits[0]["where"].startswith("TNAS › repo-archive")
    assert any(r.get("catalogue_source") == "fs" for r in records.values())


def test_pi_nudges_hub_index_after_a_tombstone(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("HUB_WORKER_TOKEN", TOKEN)
    monkeypatch.setenv("HUB_INDEX_URL", "http://ai-server:3031")
    (tmp_path / "jobs").mkdir()
    sys.path.insert(0, str(HUB_ROOT))
    import app as app_mod

    app_mod = importlib.reload(app_mod)
    sent = []
    monkeypatch.setattr(app_mod, "_nudge_hub_index", lambda: sent.append(1))
    from index_writer import append_entry

    append_entry(app_mod.DOWNLOAD_INDEX_FILE, dict(GH_RECORD, entry_id="e1", hub_job_id="jx", local_path="/mnt/tnas/x", rel_path="y"))
    assert app_mod._journal_tombstone_job({"id": "jx"}, ["/mnt/tnas/x/y"], by="purge") == ["e1"]
    assert sent == [1]
    assert app_mod._journal_tombstone_job({"id": "nothing"}, [], by="purge") == []
    assert sent == [1]  # no nudge when nothing was deleted


def _worker():
    sys.path.insert(0, str(HUB_ROOT))
    if "hub-worker" in sys.modules:
        return importlib.reload(sys.modules["hub-worker"])
    return importlib.import_module("hub-worker")


def test_worker_nudges_after_done_only(monkeypatch):
    mod = _worker()
    calls = []
    monkeypatch.setattr(mod, "hub_call", lambda *a, **k: {})
    monkeypatch.setattr(mod, "_nudge_index", lambda jid: calls.append(jid))
    mod.update_job("j1", status="running")
    mod.update_job("j1", status="done")
    assert calls == ["j1"]


def test_worker_nudge_posts_job_id_with_token(monkeypatch):
    mod = _worker()
    seen = []
    monkeypatch.setattr(mod, "WORKER_TOKEN", TOKEN)
    monkeypatch.setattr(mod, "HUB_INDEX_URL", "http://127.0.0.1:3031")
    monkeypatch.setattr(mod, "_http_json", lambda url, **kw: seen.append((url, kw)) or {})

    class Now:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(mod.threading, "Thread", Now)
    mod._nudge_index("j7")
    assert seen == [("http://127.0.0.1:3031/ingest", {"method": "POST", "body": {"job_id": "j7"}, "timeout": 2.0})]
    monkeypatch.setattr(mod, "HUB_INDEX_URL", "")
    mod._nudge_index("j8")
    assert len(seen) == 1


def _overnight():
    path = HUB_ROOT / "scripts/overnight-run.py"
    spec = importlib.util.spec_from_file_location("overnight_run_ap5a2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_i9_overnight_step_calls_rebuild_over_ssh_within_its_limit(monkeypatch):
    mod = _overnight()
    calls = []
    counts = {"ok": True, "new": 3, "changed": 1, "missing": 0, "deleted": 1, "items": 9, "files": 40,
              "snapshot": {"pushed": True}}
    monkeypatch.setattr(mod, "ssh_ubuntu", lambda cmd, timeout: calls.append((cmd, timeout)) or (0, "log line\n" + json.dumps(counts)))
    step = {"id": "index-rebuild", "type": "index_rebuild", "timeout_min": 30}
    out = mod.run_step_body(step)
    cmd, timeout = calls[0]
    assert "hub_index.py rebuild --timeout 1740" in cmd and "hub-worker.env" in cmd and timeout == 1800
    assert (out["new"], out["deleted"], out["snapshot"]["pushed"]) == (3, 1, True)
    assert mod.index_rebuild_text(out) == "3 new, 1 changed, 0 missing, 1 deleted"
    monkeypatch.setattr(mod, "ssh_ubuntu", lambda cmd, timeout: (1, json.dumps({"ok": False, "error": "hub-index not reachable"})))
    with pytest.raises(RuntimeError, match="not reachable"):
        mod.run_step_body(step)


def test_i14_step_counts_reach_the_last_night_card(monkeypatch):
    mod = _overnight()
    counts = {"ok": True, "new": 2, "changed": 0, "missing": 1, "deleted": 0, "snapshot": {"pushed": False}}
    monkeypatch.setattr(mod, "ssh_ubuntu", lambda cmd, timeout: (0, json.dumps(counts)))
    entry = mod.run_step({"id": "index-rebuild", "type": "index_rebuild", "label": "Rebuild download index", "timeout_min": 1},
                         False, "2026-10-12T12:00:00+00:00")
    assert entry["result_text"] == "2 new, 0 changed, 1 missing, 0 deleted; Pi snapshot not pushed"
    from overnight_report import _normalise_step_row

    row = _normalise_step_row({**entry, "label": "Rebuild download index", "type": "index_rebuild"})
    assert row["result_text"] == entry["result_text"]


def test_schedule_gains_the_step_once(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBS_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()
    sys.path.insert(0, str(HUB_ROOT))
    import app as app_mod

    app_mod = importlib.reload(app_mod)
    sched = {"steps": [{"id": "queue-drain", "type": "queue_drain"}, {"id": "sleep-ubuntu", "type": "machine_sleep", "target": "ubuntu"}]}
    out = app_mod._migrate_overnight_schedule(json.loads(json.dumps(sched)))
    assert [s["type"] for s in out["steps"]] == ["queue_drain", "index_rebuild", "machine_sleep"]
    out["steps"] = [s for s in out["steps"] if s["type"] != "index_rebuild"]  # Finn removes it
    again = app_mod._migrate_overnight_schedule(out)
    assert [s["type"] for s in again["steps"]] == ["queue_drain", "machine_sleep"]
    default = json.loads((HUB_ROOT / "overnight-schedule.default.json").read_text())
    types = [s["type"] for s in default["steps"]]
    assert types.index("index_rebuild") == types.index("machine_sleep") - 1


def test_manifest_and_unit():
    manifest = (HUB_ROOT / "scripts/deploy-manifest.txt").read_text()
    worker = manifest.split("[worker]")[1].split("[gateway]")[0]
    assert "hub_index.py" in worker and "scripts/systemd/hub-index.service" in worker
    unit = (HUB_ROOT / "scripts/systemd/hub-index.service").read_text()
    assert "hub_index.py serve" in unit and "EnvironmentFile=%h/homelab/scripts/hub-worker.env" in unit


def test_discover_roots(tmp_path, monkeypatch):
    (tmp_path / "ext/movies").mkdir(parents=True)
    (tmp_path / "ext/Big Drive").mkdir()
    roots = hub_index.discover_roots({"EXTERNAL_MOUNT": str(tmp_path / "ext")})
    assert [(r.root_id, r.label) for r in roots] == [
        ("tnas", "TNAS"), ("media", "Media HDD"), ("ext_big_drive", "USB Big Drive"), ("ext_movies", "Expansion HDD")
    ]
    assert [r.root_id for r in hub_index.discover_roots({"HUB_INDEX_ROOTS": "tnas=/mnt/tnas, x=/data/x/"})] == ["tnas", "x"]
