#!/usr/bin/env python3
"""AP-5a.2: the ai-server download catalogue (search over every drive).

The Pi journal (``download-index.jsonl``) and the files on disk are the truth. This module
keeps a derived SQLite (FTS5) cache on ai-server's system SSD so the Hub can text-search
everything on the TNAS and the HDDs, including files that arrived outside the Hub.
Deleting ``catalog.sqlite`` loses nothing: ``hub_index.py rebuild --local --fresh``
rebuilds it.

Rules (spec ``docs/pm/2026-10/AP-5-index-architecture-v2.md``):

- Read-only on storage: it only lists and stats. Every walk runs in a child process with a
  timeout, so a stale CIFS/USB mount cannot hang the service.
- Offline is not deleted: an unmounted root keeps its rows as ``offline``. A file becomes
  ``missing`` only when a full scan of a *mounted* root does not find it, and is purged after
  30 days. A Hub delete (journal tombstone) marks the item and its files ``deleted`` at once.
- Incremental: a folder whose mtime and link count are unchanged since the last scan is not
  listed again and its files are not re-stat'ed.

Run as ``hub_index.py serve`` (systemd user unit ``hub-index.service``). Stdlib only.
"""
from __future__ import annotations

import argparse
import gzip
import hmac
import json
import logging
import os
import queue
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from download_record import REPO_KINDS, entry_paths  # noqa: E402
from index_writer import IndexSecretError, secret_scan  # noqa: E402

log = logging.getLogger("bucket-hub.hub_index")

SCHEMA_VERSION = 1
DEFAULT_DB = Path.home() / "homelab/data/hub-index/catalog.sqlite"
DEFAULT_PORT = 3031
PURGE_DAYS = int(os.environ.get("HUB_INDEX_PURGE_DAYS", "30"))
TAIL_SECONDS = float(os.environ.get("HUB_INDEX_TAIL_S", "30"))
WALK_TIMEOUT_S = float(os.environ.get("HUB_INDEX_WALK_TIMEOUT_S", "1800"))
COMMIT_EVERY = 2000

ROOT_LABELS = {"tnas": "TNAS", "media": "Media HDD", "ext_movies": "Expansion HDD"}

SKIP_DIRS = frozenset(
    {
        "@eaDir",
        "#recycle",
        "node_modules",
        ".cache",
        ".git",
        "$RECYCLE.BIN",
        "System Volume Information",
        "lost+found",
        ".Trashes",
        ".Spotlight-V100",
        ".fseventsd",
        ".TemporaryItems",
    }
)
SKIP_FILES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
# Bare git mirrors are recorded as one opaque entry; their internals are never listed.
OPAQUE_DIR_SUFFIXES = (".git",)

# Folders whose children are "one thing each": tv/<Show>, movies/<Film>, torrents/<release>.
LIBRARY_DIRS = {"tv": "tv", "movies": "movie", "torrents": "torrent"}
REPO_DAILY_DIRS = {"github-daily": "github_repo", "huggingface-daily": "huggingface_repo"}
KIND_HINT_DIRS = {"website_backups": "website_archive", "media_archive": "video"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _skip_name(name: str, is_dir: bool) -> bool:
    if name.startswith(".partial-") or name.startswith(".hub-"):
        return True
    if is_dir:
        return name in SKIP_DIRS or name.startswith(".Trash-")
    return name in SKIP_FILES


def _join(parent: str, name: str) -> str:
    return f"{parent}/{name}" if parent else name


def _like_prefix(prefix: str) -> str:
    esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return esc + "/%"


# --- walking (runs in a child process) -------------------------------------------------


@dataclass
class WalkStats:
    stat_calls: int = 0


def walk_tree(
    root: str,
    start_rel: str = "",
    prev: dict[str, list[Any]] | None = None,
    stats: WalkStats | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield one event per folder under ``root/start_rel``.

    ``prev`` maps folder rel path -> ``[mtime_ns, nlink, subdirs]`` from the last scan. An
    unchanged folder yields ``{"d", "same": True}`` and is not listed; its known subfolders
    are still visited. A changed folder yields ``{"d", "m", "n", "subdirs", "files"}`` where
    each file is ``[name, size, mtime]`` (size ``None`` for opaque folders such as
    ``repo.git``). A folder that cannot be read yields ``{"d", "error"}``.
    """
    prev = prev or {}
    stats = stats or WalkStats()
    base = Path(root)
    stack = [start_rel.strip("/")]
    while stack:
        rel = stack.pop()
        path = base / rel if rel else base
        try:
            st = os.stat(path, follow_symlinks=False)
            stats.stat_calls += 1
        except OSError as exc:
            yield {"d": rel, "error": type(exc).__name__}
            continue
        known = prev.get(rel)
        if known and int(known[0]) == st.st_mtime_ns and int(known[1]) == st.st_nlink:
            yield {"d": rel, "same": True}
            stack.extend(_join(rel, s) for s in reversed(known[2] or []))
            continue
        subdirs: list[str] = []
        files: list[list[Any]] = []
        try:
            with os.scandir(path) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError as exc:
            yield {"d": rel, "error": type(exc).__name__}
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if _skip_name(entry.name, True):
                        continue
                    if entry.name.endswith(OPAQUE_DIR_SUFFIXES):
                        est = entry.stat(follow_symlinks=False)
                        stats.stat_calls += 1
                        files.append([entry.name, None, int(est.st_mtime)])
                        continue
                    subdirs.append(entry.name)
                elif entry.is_file(follow_symlinks=False):
                    if _skip_name(entry.name, False):
                        continue
                    est = entry.stat(follow_symlinks=False)
                    stats.stat_calls += 1
                    files.append([entry.name, est.st_size, int(est.st_mtime)])
            except OSError:
                continue
        yield {"d": rel, "m": st.st_mtime_ns, "n": st.st_nlink, "subdirs": subdirs, "files": files}
        stack.extend(_join(rel, s) for s in reversed(subdirs))


def subprocess_walker(
    root: str, start_rel: str, prev: dict[str, list[Any]], timeout_s: float
) -> tuple[list[dict[str, Any]], bool]:
    """Run ``walk_tree`` in a child process; ``(events, complete)``.

    ``complete`` is False when the child timed out or died: the caller then treats the walk as
    partial and marks nothing missing.
    """
    fd, state_path = tempfile.mkstemp(prefix="hub-index-walk-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(prev, fh)
    events: list[dict[str, Any]] = []
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "walk", root, start_rel, state_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    done = threading.Event()

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        done.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    finished = done.wait(timeout=max(1.0, timeout_s))
    complete = False
    if finished:
        try:
            complete = proc.wait(timeout=10) == 0
        except subprocess.TimeoutExpired:
            complete = False
    if not complete:
        proc.kill()  # a child stuck in D-state may never exit; do not wait on it
        log.warning("walk of %s/%s incomplete (timeout %ss)", root, start_rel, timeout_s)
    try:
        os.unlink(state_path)
    except OSError:
        pass
    return list(events), complete


def _walk_main(root: str, start_rel: str, state_path: str) -> int:
    prev = json.loads(Path(state_path).read_text(encoding="utf-8") or "{}")
    for ev in walk_tree(root, start_rel, prev):
        sys.stdout.write(json.dumps(ev, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


# --- roots -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Root:
    root_id: str
    path: str
    label: str


def discover_roots(env: dict[str, str] | None = None) -> list[Root]:
    """``HUB_INDEX_ROOTS`` (``id=path,…``) or the defaults: TNAS, Media HDD, each USB drive."""
    env = dict(os.environ if env is None else env)
    spec = env.get("HUB_INDEX_ROOTS", "").strip()
    out: list[Root] = []
    if spec:
        for part in spec.split(","):
            if "=" in part:
                rid, path = (x.strip() for x in part.split("=", 1))
                if rid and path:
                    out.append(Root(rid, path.rstrip("/") or "/", ROOT_LABELS.get(rid, rid)))
        return out
    out.append(Root("tnas", "/mnt/tnas", "TNAS"))
    out.append(Root("media", "/mnt/media", "Media HDD"))
    ext = Path(env.get("EXTERNAL_MOUNT", "/mnt/external"))
    names = _safe_list(str(ext)) or []
    for name in sorted(names):
        rid = "ext_" + "".join(c if c.isalnum() else "_" for c in name.lower())
        out.append(Root(rid, str(ext / name), ROOT_LABELS.get(rid, f"USB {name}")))
    return out


def _safe_list(path: str, timeout: int = 5) -> list[str] | None:
    try:
        r = subprocess.run(["ls", "-1", path], capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    return [x for x in r.stdout.splitlines() if x]


def is_mounted(path: str, timeout: int = 3) -> bool:
    """Mountpoint check in a child process (a stale mount cannot hang us)."""
    try:
        return subprocess.run(["mountpoint", "-q", path], timeout=timeout).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# --- grouping --------------------------------------------------------------------------


def fs_group(rel_path: str) -> tuple[str, str]:
    """``(group_rel, kind)`` for a file that no Hub record owns."""
    parts = [p for p in rel_path.split("/") if p]
    for i, seg in enumerate(parts[:-1]):
        if seg in REPO_DAILY_DIRS:
            depth = i + 4 if len(parts) > i + 1 and parts[i + 1] == "releases" else i + 3
            if len(parts) > depth - 1:
                return "/".join(parts[: min(depth, len(parts) - 1) or 1]), REPO_DAILY_DIRS[seg]
        if seg in LIBRARY_DIRS and len(parts) > i + 2:
            return "/".join(parts[: i + 2]), LIBRARY_DIRS[seg]
    kind = "folder"
    for seg in parts[:-1]:
        if seg in KIND_HINT_DIRS:
            kind = KIND_HINT_DIRS[seg]
            break
    if len(parts) == 1:
        return parts[0], "file"
    if len(parts) == 2 and parts[0] in LIBRARY_DIRS:
        return rel_path, LIBRARY_DIRS[parts[0]]  # a loose file straight under tv/ or movies/
    return "/".join(parts[:-1]), kind


def _fs_title(group_rel: str) -> str:
    name = group_rel.rstrip("/").split("/")[-1]
    return name.replace("__", "/") if "__" in name else name


# --- the catalogue ---------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS roots (
  root_id TEXT PRIMARY KEY, host_path TEXT NOT NULL, label TEXT, mounted INTEGER DEFAULT 0,
  last_full_scan TEXT, last_scan_complete INTEGER DEFAULT 0, scan_seq INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS dirs (
  root_id TEXT NOT NULL, rel_path TEXT NOT NULL, mtime_ns INTEGER, nlink INTEGER,
  subdirs TEXT, seen INTEGER DEFAULT 0, PRIMARY KEY (root_id, rel_path));
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY, root_id TEXT NOT NULL, rel_path TEXT NOT NULL, parent TEXT NOT NULL,
  name TEXT NOT NULL, ext TEXT, size INTEGER, mtime INTEGER, status TEXT NOT NULL DEFAULT 'present',
  missing_since TEXT, item_id TEXT, seen INTEGER DEFAULT 0, UNIQUE (root_id, rel_path));
CREATE INDEX IF NOT EXISTS files_parent ON files (root_id, parent);
CREATE INDEX IF NOT EXISTS files_item ON files (item_id);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY, item_id TEXT UNIQUE NOT NULL, source TEXT NOT NULL, kind TEXT,
  title TEXT, root_id TEXT, rel_path TEXT, size_bytes INTEGER, file_count INTEGER DEFAULT 0,
  mtime INTEGER, status TEXT NOT NULL, record TEXT, updated_at TEXT, deleted_at TEXT);
CREATE INDEX IF NOT EXISTS items_root ON items (root_id, rel_path);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_items USING fts5(title, tags, description, note, excerpt, path);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_files USING fts5(name, path);
"""

# bm25 column weights for fts_items (spec A6: title 3, tags/topics 2, description/note 1.5,
# excerpt 1, path 1).
ITEM_WEIGHTS = (3.0, 2.0, 1.5, 1.5, 1.0, 1.0)
HIDDEN_BY_DEFAULT = ("deleted", "failed")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value if v is not None)
    return str(value)


def fts_query(q: str) -> str:
    """Each term quoted and prefix-matched; FTS5 ANDs them. No FTS syntax reaches SQLite."""
    terms = [t for t in (q or "").replace('"', " ").split() if t.strip()]
    return " ".join(f'"{t}"*' for t in terms)


Walker = Callable[[str, str, dict[str, list[Any]], float], tuple[list[dict[str, Any]], bool]]


class Catalogue:
    def __init__(
        self,
        db_path: str | Path,
        *,
        roots: list[Root] | None = None,
        archive_root: str = "",
        mounted: Callable[[str], bool] = is_mounted,
        walker: Walker = subprocess_walker,
    ) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._roots = roots
        self.archive_root = archive_root or os.environ.get("HUB_REPO_ARCHIVE_ROOT", "/mnt/tnas/repo-archive")
        self.mounted = mounted
        self.walker = walker
        self.work_lock = threading.RLock()  # one writer at a time (ingest, scans, purge)
        self._local = threading.local()
        with self.work_lock:
            db = self.db
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            db.commit()

    # connections: one per thread; WAL lets searches run while a scan writes
    @property
    def db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def meta(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))

    def roots(self) -> list[Root]:
        return list(self._roots) if self._roots is not None else discover_roots()

    def _root_rows(self) -> dict[str, sqlite3.Row]:
        return {r["root_id"]: r for r in self.db.execute("SELECT * FROM roots")}

    def _ensure_root(self, root: Root) -> None:
        self.db.execute(
            "INSERT INTO roots (root_id, host_path, label) VALUES (?, ?, ?) "
            "ON CONFLICT(root_id) DO UPDATE SET host_path=excluded.host_path, label=excluded.label",
            (root.root_id, root.path, root.label),
        )

    def locate(self, abs_path: str) -> tuple[str, str] | None:
        """``(root_id, rel_path)`` for an absolute path, longest root first."""
        p = str(abs_path).rstrip("/")
        best: tuple[str, str] | None = None
        best_len = -1
        for r in self.db.execute("SELECT root_id, host_path FROM roots"):
            hp = r["host_path"].rstrip("/")
            if (p == hp or p.startswith(hp + "/")) and len(hp) > best_len:
                best, best_len = (r["root_id"], p[len(hp) :].strip("/")), len(hp)
        return best

    def where(self, root_id: str | None, rel_path: str | None, status: str = "") -> str:
        if not root_id:
            return ""
        row = self.db.execute("SELECT label, mounted FROM roots WHERE root_id=?", (root_id,)).fetchone()
        label = (row["label"] if row else None) or root_id
        parts = [p for p in (rel_path or "").split("/") if p]
        text = label
        if parts:
            text += " › " + parts[0]
        if len(parts) > 1:
            text += " › " + "/".join(parts[1:])
        if status == "offline" or (row is not None and not row["mounted"]):
            text += " (offline)"
        return text

    # --- journal ingest ------------------------------------------------------------------

    def _own_location(self, rec: dict[str, Any]) -> tuple[str, str] | None:
        """Where a Hub record's own folder or file lives, if it is specific to that record.

        A record whose only path is a shared destination (``local_path`` without a
        ``rel_path``) owns no files: it stays a journal-only item.
        """
        rel = str(rec.get("rel_path") or "").strip()
        if not rel and rec.get("kind") not in REPO_KINDS:
            return None
        paths = entry_paths(rec, self.archive_root)
        if not paths:
            return None
        return self.locate(paths[-1])

    def upsert_record(self, rec: dict[str, Any]) -> str:
        """Insert or update a Hub item from a merged journal record; returns the transition."""
        eid = str(rec.get("entry_id") or "")
        if not eid:
            return "skipped"
        db = self.db
        prev = db.execute("SELECT id, status FROM items WHERE item_id=?", (eid,)).fetchone()
        loc = self._own_location(rec)
        root_id, rel = loc if loc else (None, None)
        rstatus = str(rec.get("status") or "")
        status = rstatus if rstatus in HIDDEN_BY_DEFAULT else (prev["status"] if prev and prev["status"] not in HIDDEN_BY_DEFAULT else "recorded")
        title = rec.get("full_name") or rec.get("title") or rec.get("repo_id") or rec.get("release_name") or eid
        args = (
            rec.get("kind"),
            str(title),
            root_id,
            rel,
            rec.get("size_bytes"),
            status,
            json.dumps(rec, ensure_ascii=False),
            _now(),
            rec.get("deleted_at") if rstatus == "deleted" else None,
        )
        if prev:
            db.execute(
                "UPDATE items SET kind=?, title=?, root_id=?, rel_path=?, size_bytes=?, status=?, record=?, "
                "updated_at=?, deleted_at=?, source='hub' WHERE item_id=?",
                (*args, eid),
            )
        else:
            db.execute(
                "INSERT INTO items (kind, title, root_id, rel_path, size_bytes, status, record, updated_at, "
                "deleted_at, source, item_id) VALUES (?,?,?,?,?,?,?,?,?, 'hub', ?)",
                (*args, eid),
            )
        if loc:
            # an fs-only item at the same place is superseded by the Hub record
            db.execute(
                "DELETE FROM items WHERE source='fs' AND root_id=? AND rel_path=? AND item_id<>?",
                (root_id, rel, eid),
            )
        if rstatus == "deleted":
            db.execute("UPDATE files SET status='deleted' WHERE item_id=? AND status<>'deleted'", (eid,))
            if loc:
                db.execute(
                    "UPDATE files SET status='deleted' WHERE root_id=? AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\') "
                    "AND status<>'deleted'",
                    (root_id, rel, _like_prefix(rel or "")),
                )
        transition = "new" if not prev else "changed"
        if rstatus == "deleted" and (not prev or prev["status"] != "deleted"):
            transition = "deleted"
        return transition

    def sync_roots(self) -> list[Root]:
        roots = self.roots()
        for r in roots:
            self._ensure_root(r)
        return roots

    def relocate(self) -> int:
        """Place Hub items whose root was unknown when they were ingested (a drive plugged in later)."""
        moved: list[str] = []
        for row in self.db.execute("SELECT item_id, record FROM items WHERE source='hub' AND root_id IS NULL").fetchall():
            try:
                rec = json.loads(row["record"] or "{}")
            except json.JSONDecodeError:
                continue
            loc = self._own_location(rec)
            if loc:
                self.db.execute("UPDATE items SET root_id=?, rel_path=? WHERE item_id=?", (*loc, row["item_id"]))
                self.db.execute(
                    "DELETE FROM items WHERE source='fs' AND root_id=? AND rel_path=?", loc
                )
                moved.append(row["item_id"])
        if moved:
            self._regroup_for_items(moved)
        return len(moved)

    def ingest_records(self, records: Iterable[dict[str, Any]]) -> dict[str, int]:
        counts = {"records": 0, "new": 0, "changed": 0, "deleted": 0}
        touched: list[str] = []
        with self.work_lock:
            self.sync_roots()
            for rec in records:
                t = self.upsert_record(rec)
                if t == "skipped":
                    continue
                counts["records"] += 1
                counts[t] = counts.get(t, 0) + 1
                touched.append(str(rec["entry_id"]))
            self._regroup_for_items(touched)
            self.db.commit()
        return counts

    def tail_journal(self, fetch: Callable[[int], tuple[list[dict[str, Any]], int]]) -> dict[str, int]:
        """Pull records changed since the stored cursor; a shrunken journal resets the cursor."""
        with self.work_lock:
            cursor = int(self.meta("journal_cursor", "0") or 0)
            rows, new_cursor = fetch(cursor)
            if new_cursor < cursor:
                log.warning("journal shrank (%s < %s): re-reading from the start", new_cursor, cursor)
                rows, new_cursor = fetch(0)
            counts = self.ingest_records(rows)
            self.set_meta("journal_cursor", new_cursor)
            self.set_meta("last_ingest", _now())
            self.db.commit()
        counts["cursor"] = new_cursor
        return counts

    def hub_dirs_for_job(self, job_id: str) -> list[tuple[str, str]]:
        out = []
        for row in self.db.execute("SELECT root_id, rel_path, record FROM items WHERE source='hub' AND root_id IS NOT NULL"):
            try:
                rec = json.loads(row["record"] or "{}")
            except json.JSONDecodeError:
                continue
            if str(rec.get("hub_job_id") or "") == job_id:
                out.append((row["root_id"], row["rel_path"] or ""))
        return out

    # --- grouping files into items -------------------------------------------------------

    def _hub_prefixes(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for r in self.db.execute("SELECT item_id, root_id, rel_path FROM items WHERE source='hub' AND root_id IS NOT NULL"):
            out.setdefault(r["root_id"], {})[r["rel_path"] or ""] = r["item_id"]
        return out

    def _owner(self, prefixes: dict[str, dict[str, str]], root_id: str, rel: str) -> tuple[str, str, str | None]:
        """``(item_id, group_rel, fs_kind)``; fs_kind is None for a Hub-owned file."""
        mine = prefixes.get(root_id) or {}
        parts = rel.split("/")
        for n in range(len(parts), 0, -1):
            pre = "/".join(parts[:n])
            if pre in mine:
                return mine[pre], pre, None
        group, kind = fs_group(rel)
        return f"fs:{root_id}:{group}", group, kind

    def regroup(self, root_id: str | None = None, prefix: str | None = None) -> set[str]:
        """Recompute ``files.item_id``; returns every item id whose membership changed."""
        prefixes = self._hub_prefixes()
        sql = "SELECT id, root_id, rel_path, item_id FROM files"
        args: list[Any] = []
        if root_id:
            sql += " WHERE root_id=?"
            args.append(root_id)
            if prefix:
                sql += " AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')"
                args += [prefix, _like_prefix(prefix)]
        changed: set[str] = set()
        fs_new: dict[str, tuple[str, str, str]] = {}
        updates: list[tuple[str, int]] = []
        for f in self.db.execute(sql, args).fetchall():
            item_id, group, fs_kind = self._owner(prefixes, f["root_id"], f["rel_path"])
            if fs_kind is not None:
                fs_new[item_id] = (f["root_id"], group, fs_kind)
            if f["item_id"] != item_id:
                updates.append((item_id, f["id"]))
                changed.add(item_id)
                if f["item_id"]:
                    changed.add(f["item_id"])
        self.db.executemany("UPDATE files SET item_id=? WHERE id=?", updates)
        for item_id, (rid, group, kind) in fs_new.items():
            if item_id in changed:
                self.db.execute(
                    "INSERT OR IGNORE INTO items (item_id, source, kind, title, root_id, rel_path, status, updated_at) "
                    "VALUES (?, 'fs', ?, ?, ?, ?, 'present', ?)",
                    (item_id, kind, _fs_title(group), rid, group, _now()),
                )
        self.refresh_items(changed)
        return changed

    def _regroup_for_items(self, item_ids: list[str]) -> None:
        roots_prefixes: set[tuple[str, str]] = set()
        for iid in item_ids:
            row = self.db.execute("SELECT root_id, rel_path FROM items WHERE item_id=?", (iid,)).fetchone()
            if row and row["root_id"]:
                roots_prefixes.add((row["root_id"], row["rel_path"] or ""))
        for rid, pre in roots_prefixes:
            self.regroup(rid, pre or None)
        self.refresh_items(set(item_ids))

    def refresh_items(self, item_ids: Iterable[str]) -> None:
        """Recompute size, counts and status for these items; keep FTS rows in step."""
        for iid in set(item_ids):
            item = self.db.execute("SELECT * FROM items WHERE item_id=?", (iid,)).fetchone()
            if item is None:
                continue
            agg = self.db.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN status IN ('present','offline') THEN size END),0) AS sz, "
                "MAX(mtime) AS mt, SUM(status='present') AS p, SUM(status='offline') AS o, SUM(status='missing') AS m "
                "FROM files WHERE item_id=? AND status<>'deleted'",
                (iid,),
            ).fetchone()
            n = agg["n"] or 0
            if item["source"] == "fs" and n == 0:
                self.db.execute("DELETE FROM fts_items WHERE rowid=?", (item["id"],))
                self.db.execute("DELETE FROM items WHERE id=?", (item["id"],))
                continue
            status = item["status"]
            if status not in HIDDEN_BY_DEFAULT:
                if agg["p"]:
                    status = "present"
                elif agg["o"]:
                    status = "offline"
                elif agg["m"]:
                    status = "missing"
                else:
                    status = "recorded"
            size = agg["sz"] or 0
            if item["source"] == "hub":
                # an opaque repo.git has no size of its own: the journal's size is the better figure
                try:
                    rec_size = int(json.loads(item["record"] or "{}").get("size_bytes") or 0)
                except (ValueError, TypeError, json.JSONDecodeError):
                    rec_size = 0
                size = max(size, rec_size) or None
            self.db.execute(
                "UPDATE items SET status=?, file_count=?, size_bytes=?, mtime=? WHERE id=?",
                (status, n, size, agg["mt"], item["id"]),
            )
            self._fts_item(item["id"])

    def _fts_item(self, rowid: int) -> None:
        item = self.db.execute("SELECT * FROM items WHERE id=?", (rowid,)).fetchone()
        self.db.execute("DELETE FROM fts_items WHERE rowid=?", (rowid,))
        if item is None:
            return
        rec: dict[str, Any] = {}
        if item["record"]:
            try:
                rec = json.loads(item["record"])
            except json.JSONDecodeError:
                rec = {}
        title = " ".join(
            _text(rec.get(k)) for k in ("full_name", "title", "repo_id", "release_name", "show_title")
        ) or (item["title"] or "")
        tags = " ".join(
            _text(rec.get(k)) for k in ("hub_tags", "topics", "pipeline_tag", "library_name", "segment")
        ) + f" {item['kind'] or ''}"
        desc = _text(rec.get("description"))
        note = f"{_text(rec.get('user_note'))} {_text(rec.get('context'))}"
        excerpt = _text(rec.get("readme_excerpt"))
        path = f"{item['rel_path'] or ''} {_text(rec.get('local_path'))} {_text(rec.get('rel_path'))}"
        self.db.execute(
            "INSERT INTO fts_items (rowid, title, tags, description, note, excerpt, path) VALUES (?,?,?,?,?,?,?)",
            (rowid, title, tags, desc, note, excerpt, path),
        )

    # --- scanning ------------------------------------------------------------------------

    def _prev_dirs(self, root_id: str, prefix: str) -> dict[str, list[Any]]:
        sql = "SELECT rel_path, mtime_ns, nlink, subdirs FROM dirs WHERE root_id=?"
        args: list[Any] = [root_id]
        if prefix:
            sql += " AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')"
            args += [prefix, _like_prefix(prefix)]
        return {
            r["rel_path"]: [r["mtime_ns"], r["nlink"], json.loads(r["subdirs"] or "[]")]
            for r in self.db.execute(sql, args)
        }

    def scan_root(self, root: Root, prefix: str = "", timeout_s: float = WALK_TIMEOUT_S) -> dict[str, Any]:
        """Scan one root (or one folder under it); returns counts. Never writes to the drive."""
        prefix = prefix.strip("/")
        with self.work_lock:
            db = self.db
            self._ensure_root(root)
            if not self.mounted(root.path):
                n = db.execute(
                    "UPDATE files SET status='offline' WHERE root_id=? AND status='present'", (root.root_id,)
                ).rowcount
                db.execute("UPDATE roots SET mounted=0 WHERE root_id=?", (root.root_id,))
                touched = {r["item_id"] for r in db.execute(
                    "SELECT DISTINCT item_id FROM files WHERE root_id=? AND item_id IS NOT NULL", (root.root_id,))}
                self.refresh_items(touched)
                db.commit()
                return {"root_id": root.root_id, "mounted": False, "offline": n, "new": 0, "changed": 0, "missing": 0}
            db.execute("UPDATE roots SET mounted=1 WHERE root_id=?", (root.root_id,))
            seq = (db.execute("SELECT scan_seq FROM roots WHERE root_id=?", (root.root_id,)).fetchone()["scan_seq"] or 0) + 1
            db.execute("UPDATE roots SET scan_seq=? WHERE root_id=?", (seq, root.root_id))
            prev = self._prev_dirs(root.root_id, prefix)
            t0 = time.time()
            events, complete = self.walker(root.path, prefix, prev, timeout_s)
            counts = {"root_id": root.root_id, "mounted": True, "new": 0, "changed": 0, "missing": 0,
                      "dirs": 0, "same_dirs": 0, "errors": 0, "complete": complete}
            present_before = db.execute(
                "SELECT COUNT(*) FROM files WHERE root_id=? AND status IN ('present','offline')", (root.root_id,)
            ).fetchone()[0]
            fts_dirty: list[int] = []
            pending = 0
            seen_files = 0
            for ev in events:
                rel = ev.get("d", "")
                if ev.get("error"):
                    counts["errors"] += 1
                    # unreadable folder: keep what we knew (mark its subtree seen)
                    db.execute(
                        "UPDATE files SET seen=? WHERE root_id=? AND (parent=? OR parent LIKE ? ESCAPE '\\')",
                        (seq, root.root_id, rel, _like_prefix(rel) if rel else "%"),
                    )
                    db.execute(
                        "UPDATE dirs SET seen=? WHERE root_id=? AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')",
                        (seq, root.root_id, rel, _like_prefix(rel) if rel else "%"),
                    )
                    continue
                counts["dirs"] += 1
                if ev.get("same"):
                    counts["same_dirs"] += 1
                    seen_files += db.execute(
                        "UPDATE files SET seen=?, status=CASE WHEN status='offline' THEN 'present' ELSE status END, "
                        "missing_since=CASE WHEN status='offline' THEN NULL ELSE missing_since END "
                        "WHERE root_id=? AND parent=?",
                        (seq, root.root_id, rel),
                    ).rowcount
                    db.execute("UPDATE dirs SET seen=? WHERE root_id=? AND rel_path=?", (seq, root.root_id, rel))
                    continue
                db.execute(
                    "INSERT INTO dirs (root_id, rel_path, mtime_ns, nlink, subdirs, seen) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(root_id, rel_path) DO UPDATE SET mtime_ns=excluded.mtime_ns, nlink=excluded.nlink, "
                    "subdirs=excluded.subdirs, seen=excluded.seen",
                    (root.root_id, rel, ev.get("m"), ev.get("n"), json.dumps(ev.get("subdirs") or []), seq),
                )
                for name, size, mtime in ev.get("files") or []:
                    frel = _join(rel, name)
                    seen_files += 1
                    old = db.execute(
                        "SELECT id, size, mtime, status FROM files WHERE root_id=? AND rel_path=?", (root.root_id, frel)
                    ).fetchone()
                    ext = name.rsplit(".", 1)[-1].lower() if "." in name.strip(".") else ""
                    if old is None:
                        cur = db.execute(
                            "INSERT INTO files (root_id, rel_path, parent, name, ext, size, mtime, status, seen) "
                            "VALUES (?,?,?,?,?,?,?, 'present', ?)",
                            (root.root_id, frel, rel, name, ext, size, mtime, seq),
                        )
                        counts["new"] += 1
                        fts_dirty.append(int(cur.lastrowid))
                    else:
                        revived = old["status"] in ("missing", "deleted")
                        if revived or old["size"] != size or old["mtime"] != mtime:
                            counts["changed"] += 1
                        db.execute(
                            "UPDATE files SET size=?, mtime=?, seen=?, status='present', missing_since=NULL WHERE id=?",
                            (size, mtime, seq, old["id"]),
                        )
                    pending += 1
                if pending >= COMMIT_EVERY:
                    db.commit()
                    pending = 0
            for fid in fts_dirty:
                f = db.execute("SELECT name, rel_path FROM files WHERE id=?", (fid,)).fetchone()
                db.execute("INSERT INTO fts_files (rowid, name, path) VALUES (?,?,?)", (fid, f["name"], f["rel_path"]))
            scope_sql = " AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')" if prefix else ""
            scope_args = [prefix, _like_prefix(prefix)] if prefix else []
            if complete and not counts["errors"] and seen_files == 0 and present_before > 100 and not prefix:
                # an empty listing of a big root is a mount problem, not a mass delete
                log.warning("root %s listed empty but had %s files: treating as offline", root.root_id, present_before)
                db.execute("UPDATE files SET status='offline' WHERE root_id=? AND status='present'", (root.root_id,))
                counts["suspect_empty"] = True
            elif complete:
                counts["missing"] = db.execute(
                    "UPDATE files SET status='missing', missing_since=? WHERE root_id=? AND seen<? "
                    "AND status IN ('present','offline')" + scope_sql,
                    (_now(), root.root_id, seq, *scope_args),
                ).rowcount
                db.execute("DELETE FROM dirs WHERE root_id=? AND seen<?" + scope_sql, (root.root_id, seq, *scope_args))
            if not prefix:
                db.execute(
                    "UPDATE roots SET last_full_scan=?, last_scan_complete=? WHERE root_id=?",
                    (_now(), int(complete), root.root_id),
                )
            self.regroup(root.root_id, prefix or None)
            touched = {r["item_id"] for r in db.execute(
                "SELECT DISTINCT item_id FROM files WHERE root_id=? AND item_id IS NOT NULL" + scope_sql,
                (root.root_id, *scope_args))}
            self.refresh_items(touched)
            db.commit()
            counts["secs"] = round(time.time() - t0, 2)
            return counts

    def scan_path(self, abs_path: str, timeout_s: float = 120) -> dict[str, Any] | None:
        """Scan one download folder (after a worker nudge)."""
        for r in self.roots():
            with self.work_lock:
                self._ensure_root(r)
        loc = self.locate(abs_path)
        if loc is None:
            return None
        root = next((r for r in self.roots() if r.root_id == loc[0]), None)
        return self.scan_root(root, loc[1], timeout_s) if root else None

    def purge(self, days: int = PURGE_DAYS) -> dict[str, int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.work_lock:
            db = self.db
            gone = [r["id"] for r in db.execute(
                "SELECT id FROM files WHERE status IN ('missing','deleted') AND missing_since IS NOT NULL AND missing_since<?",
                (cutoff,))]
            gone += [r["id"] for r in db.execute(
                "SELECT f.id FROM files f JOIN items i ON i.item_id=f.item_id WHERE f.status='deleted' "
                "AND i.deleted_at IS NOT NULL AND i.deleted_at<?", (cutoff,))]
            for fid in set(gone):
                db.execute("DELETE FROM fts_files WHERE rowid=?", (fid,))
                db.execute("DELETE FROM files WHERE id=?", (fid,))
            items = [r for r in db.execute(
                "SELECT id FROM items WHERE status='deleted' AND deleted_at IS NOT NULL AND deleted_at<?", (cutoff,))]
            for r in items:
                db.execute("DELETE FROM fts_items WHERE rowid=?", (r["id"],))
                db.execute("DELETE FROM items WHERE id=?", (r["id"],))
            db.commit()
            return {"files": len(set(gone)), "items": len(items)}

    def rebuild(
        self,
        fetch: Callable[[int], tuple[list[dict[str, Any]], int]] | None = None,
        push: Callable[[bytes], dict[str, Any]] | None = None,
        timeout_s: float = WALK_TIMEOUT_S,
    ) -> dict[str, Any]:
        """Nightly: journal tail, incremental full scan of every root, purge, snapshot push."""
        t0 = time.time()
        deadline = t0 + timeout_s
        out: dict[str, Any] = {"new": 0, "changed": 0, "missing": 0, "deleted": 0, "roots": {}}
        with self.work_lock:
            if fetch is not None:
                try:
                    j = self.tail_journal(fetch)
                    out["deleted"] += j.get("deleted", 0)
                    out["journal"] = j
                except Exception as exc:  # noqa: BLE001
                    out["journal"] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
            for root in self.roots():
                remain = deadline - time.time()
                if remain <= 5:
                    out["roots"][root.root_id] = {"skipped": "time limit"}
                    continue
                c = self.scan_root(root, "", remain)
                out["roots"][root.root_id] = c
                for k in ("new", "changed", "missing"):
                    out[k] += int(c.get(k) or 0)
            out["relocated"] = self.relocate()
            out["purged"] = self.purge()
            self.regroup()
            self.db.commit()
            self.set_meta("last_rebuild", _now())
            self.db.commit()
        out["items"], out["files"] = self.totals()
        if push is not None:
            try:
                out["snapshot"] = push(self.snapshot_bytes())
            except Exception as exc:  # noqa: BLE001
                out["snapshot"] = {"pushed": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        out["secs"] = round(time.time() - t0, 1)
        return out

    # --- reading -------------------------------------------------------------------------

    def totals(self) -> tuple[int, int]:
        items = self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        files = self.db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        return items, files

    def _item_row(self, r: sqlite3.Row, score: float | None = None) -> dict[str, Any]:
        rec = json.loads(r["record"]) if r["record"] else None
        row = {
            "item_id": r["item_id"],
            "source": r["source"],
            "kind": r["kind"],
            "title": r["title"],
            "status": r["status"],
            "root_id": r["root_id"],
            "rel_path": r["rel_path"],
            "where": self.where(r["root_id"], r["rel_path"], r["status"]) or _text((rec or {}).get("saves_to") or (rec or {}).get("local_path")),
            "size_bytes": r["size_bytes"],
            "file_count": r["file_count"],
            "mtime": r["mtime"],
            "record": rec,
        }
        if score is not None:
            row["score"] = round(-score, 4)
        return row

    def _status_filter(self, alias: str, status: str) -> tuple[str, list[Any]]:
        if status:
            return f" AND {alias}.status=?", [status]
        return f" AND {alias}.status NOT IN ({','.join('?' * len(HIDDEN_BY_DEFAULT))})", list(HIDDEN_BY_DEFAULT)

    def search(
        self,
        q: str = "",
        *,
        kind: str = "",
        root: str = "",
        status: str = "",
        scope: str = "items",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))
        out: dict[str, Any] = {"q": q, "scope": scope, "source": "catalogue"}
        match = fts_query(q)
        if scope in ("items", "all"):
            where, args = self._status_filter("i", status)
            if kind:
                where += " AND i.kind=?"
                args.append(kind)
            if root:
                where += " AND i.root_id=?"
                args.append(root)
            if match:
                w = ",".join(str(x) for x in ITEM_WEIGHTS)
                base = f"FROM fts_items JOIN items i ON i.id=fts_items.rowid WHERE fts_items MATCH ?{where}"
                total = self.db.execute(f"SELECT COUNT(*) {base}", [match, *args]).fetchone()[0]
                rows = self.db.execute(
                    f"SELECT i.*, bm25(fts_items, {w}) AS rank {base} ORDER BY rank LIMIT ? OFFSET ?",
                    [match, *args, limit, offset],
                ).fetchall()
                items = [self._item_row(r, r["rank"]) for r in rows]
            else:
                base = f"FROM items i WHERE 1=1{where}"
                total = self.db.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
                rows = self.db.execute(
                    f"SELECT i.* {base} ORDER BY i.updated_at DESC, i.mtime DESC LIMIT ? OFFSET ?", [*args, limit, offset]
                ).fetchall()
                items = [self._item_row(r) for r in rows]
            out["total"] = total
            out["items"] = _clean_rows(items)
        if scope in ("files", "all") and match:
            where, args = self._status_filter("f", status)
            if root:
                where += " AND f.root_id=?"
                args.append(root)
            if kind:
                where += " AND i.kind=?"
                args.append(kind)
            base = (
                "FROM fts_files JOIN files f ON f.id=fts_files.rowid LEFT JOIN items i ON i.item_id=f.item_id "
                f"WHERE fts_files MATCH ?{where}"
            )
            out["files_total"] = self.db.execute(f"SELECT COUNT(*) {base}", [match, *args]).fetchone()[0]
            rows = self.db.execute(
                f"SELECT f.*, i.title AS item_title, i.kind AS item_kind, bm25(fts_files) AS rank {base} "
                "ORDER BY rank LIMIT ? OFFSET ?",
                [match, *args, limit, offset],
            ).fetchall()
            out["files"] = _clean_rows(
                [
                    {
                        "root_id": r["root_id"],
                        "rel_path": r["rel_path"],
                        "name": r["name"],
                        "size": r["size"],
                        "mtime": r["mtime"],
                        "status": r["status"],
                        "where": self.where(r["root_id"], r["rel_path"], r["status"]),
                        "item": {"item_id": r["item_id"], "title": r["item_title"], "kind": r["item_kind"]},
                    }
                    for r in rows
                ]
            )
        return out

    def item(self, item_id: str, max_files: int = 200) -> dict[str, Any] | None:
        r = self.db.execute("SELECT * FROM items WHERE item_id=?", (item_id,)).fetchone()
        if r is None:
            return None
        row = self._item_row(r)
        row["files"] = [
            {"rel_path": f["rel_path"], "size": f["size"], "mtime": f["mtime"], "status": f["status"]}
            for f in self.db.execute(
                "SELECT rel_path, size, mtime, status FROM files WHERE item_id=? ORDER BY rel_path LIMIT ?",
                (item_id, max_files),
            )
        ]
        cleaned = _clean_rows([row])
        return cleaned[0] if cleaned else None

    def health(self) -> dict[str, Any]:
        items, files = self.totals()
        roots = []
        for r in self.db.execute("SELECT * FROM roots ORDER BY root_id"):
            c = {
                s: n
                for s, n in self.db.execute(
                    "SELECT status, COUNT(*) FROM files WHERE root_id=? GROUP BY status", (r["root_id"],)
                )
            }
            roots.append(
                {
                    "root_id": r["root_id"],
                    "path": r["host_path"],
                    "label": r["label"],
                    "mounted": bool(r["mounted"]),
                    "last_full_scan": r["last_full_scan"],
                    "last_scan_complete": bool(r["last_scan_complete"]),
                    "files": c,
                }
            )
        db_bytes = Path(self.db_path).stat().st_size if Path(self.db_path).exists() else 0
        return {
            "ok": True,
            "schema_version": int(self.meta("schema_version", "0") or 0),
            "items": items,
            "files": files,
            "roots": roots,
            "journal_cursor": int(self.meta("journal_cursor", "0") or 0),
            "last_ingest": self.meta("last_ingest") or None,
            "last_rebuild": self.meta("last_rebuild") or None,
            "db_path": self.db_path,
            "db_bytes": db_bytes,
        }

    def snapshot_bytes(self) -> bytes:
        """Gzip JSONL of every item (no file rows) for the Pi fallback search."""
        lines = []
        for r in self.db.execute("SELECT * FROM items ORDER BY id"):
            rec = json.loads(r["record"]) if r["record"] else {}
            line = dict(rec)
            line.update(
                {
                    "entry_id": r["item_id"],
                    "kind": r["kind"],
                    "title": rec.get("title") or r["title"],
                    "status": r["status"],
                    "where": self.where(r["root_id"], r["rel_path"], r["status"]),
                    "size_bytes": r["size_bytes"],
                    "catalogue_source": r["source"],
                }
            )
            try:
                secret_scan(line)
            except IndexSecretError:
                log.warning("snapshot: dropped %s (secret marker)", r["item_id"])
                continue
            lines.append(json.dumps(line, ensure_ascii=False))
        return gzip.compress(("\n".join(lines) + ("\n" if lines else "")).encode("utf-8"))


def _clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Never return a row that would leak a secret (``secret_scan`` on output)."""
    out = []
    for row in rows:
        try:
            secret_scan(row)
        except IndexSecretError:
            log.warning("search: dropped a row with a secret marker (%s)", row.get("item_id") or row.get("rel_path"))
            continue
        out.append(row)
    return out


# --- talking to the Pi -----------------------------------------------------------------


def hub_urls(env: dict[str, str] | None = None) -> list[str]:
    env = dict(os.environ if env is None else env)
    raw = env.get("HUB_URL", "http://192.168.50.138:3020,http://100.85.42.0:3020")
    return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]


def pi_fetch(since: int, *, timeout: float = 30) -> tuple[list[dict[str, Any]], int]:
    """``GET /api/index/export?since=`` on the Pi (each HUB_URL in turn)."""
    last: Exception | None = None
    for base in hub_urls():
        try:
            req = urllib.request.Request(f"{base}/api/index/export?since={int(since)}", headers={"Accept": "application/x-ndjson"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                cursor = int(resp.headers.get("X-Index-Cursor") or since)
                rows = [json.loads(line) for line in resp.read().decode("utf-8").splitlines() if line.strip()]
            return rows, cursor
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last or RuntimeError("no HUB_URL")


def pi_push_snapshot(data: bytes, *, timeout: float = 60) -> dict[str, Any]:
    token = os.environ.get("HUB_WORKER_TOKEN", "")
    last: Exception | None = None
    for base in hub_urls():
        try:
            req = urllib.request.Request(
                f"{base}/api/index/snapshot",
                data=data,
                method="PUT",
                headers={"Content-Type": "application/gzip", "X-Worker-Token": token},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8") or "{}")
            return {"pushed": True, **{k: body.get(k) for k in ("items", "bytes")}}
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last or RuntimeError("no HUB_URL")


# --- HTTP service ----------------------------------------------------------------------


class Service:
    """The catalogue plus its background loop (journal tail every 30 s, nudges)."""

    def __init__(self, cat: Catalogue, token: str, fetch=pi_fetch, push=pi_push_snapshot) -> None:
        self.cat = cat
        self.token = token
        self.fetch = fetch
        self.push = push
        self.nudges: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.stop = threading.Event()
        self.last_error = ""

    def handle_nudge(self, body: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        try:
            out["journal"] = self.cat.tail_journal(self.fetch)
        except Exception as exc:  # noqa: BLE001
            out["journal"] = {"error": f"{type(exc).__name__}"}
        scans = []
        targets: list[str] = []
        if body.get("download_dir"):
            targets.append(str(body["download_dir"]))
        if body.get("job_id"):
            for rid, rel in self.cat.hub_dirs_for_job(str(body["job_id"])):
                row = self.cat.db.execute("SELECT host_path FROM roots WHERE root_id=?", (rid,)).fetchone()
                if row:
                    targets.append(f"{row['host_path'].rstrip('/')}/{rel}".rstrip("/"))
        for t in dict.fromkeys(targets):
            r = self.cat.scan_path(t)
            if r:
                scans.append(r)
        out["scans"] = scans
        return out

    def loop(self) -> None:
        if not self.cat.meta("last_rebuild"):
            log.info("first start: full rebuild")
            try:
                self.cat.rebuild(self.fetch, self.push)
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"first rebuild: {type(exc).__name__}: {exc}"[:300]
                log.exception("first rebuild failed")
        while not self.stop.is_set():
            try:
                body = self.nudges.get(timeout=TAIL_SECONDS)
            except queue.Empty:
                body = None
            try:
                if body is None:
                    self.cat.tail_journal(self.fetch)
                else:
                    self.handle_nudge(body)
                self.last_error = ""
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("index loop: %s", self.last_error)

    def authorised(self, header: str | None) -> bool:
        return bool(self.token) and bool(header) and hmac.compare_digest(str(header), self.token)


def make_handler(svc: Service) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "hub-index/1"

        def log_message(self, fmt: str, *args: Any) -> None:  # quiet; journald gets errors only
            pass

        def _send(self, code: int, body: Any) -> None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            data = json.loads(self.rfile.read(min(n, 65536)).decode("utf-8") or "{}")
            return data if isinstance(data, dict) else {}

        def handle_one_request(self) -> None:
            try:
                super().handle_one_request()
            finally:
                svc.cat.close()  # each request runs on its own thread: do not leave its connection open

        def do_GET(self) -> None:  # noqa: N802
            url = urllib.parse.urlparse(self.path)
            qs = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query).items()}
            try:
                if url.path == "/health":
                    h = svc.cat.health()
                    h["last_error"] = svc.last_error or None
                    return self._send(200, h)
                if url.path == "/search":
                    return self._send(
                        200,
                        svc.cat.search(
                            qs.get("q", ""),
                            kind=qs.get("kind", ""),
                            root=qs.get("root", ""),
                            status=qs.get("status", ""),
                            scope=qs.get("scope", "items") if qs.get("scope") in ("items", "files", "all") else "items",
                            limit=int(qs.get("limit", "50") or 50),
                            offset=int(qs.get("offset", "0") or 0),
                        ),
                    )
                if url.path.startswith("/item/"):
                    item = svc.cat.item(urllib.parse.unquote(url.path[len("/item/") :]))
                    return self._send(200, item) if item else self._send(404, {"error": "not found"})
            except ValueError:
                return self._send(400, {"error": "bad parameter"})
            except sqlite3.OperationalError as exc:
                return self._send(400, {"error": f"search error: {exc}"[:200]})
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            if path not in ("/ingest", "/rebuild"):
                return self._send(404, {"error": "not found"})
            if not svc.authorised(self.headers.get("X-Worker-Token")):
                return self._send(401, {"error": "worker token required"})
            try:
                body = self._body()
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {"error": "bad json"})
            if path == "/ingest":
                svc.nudges.put({k: body.get(k) for k in ("job_id", "download_dir") if body.get(k)})
                return self._send(202, {"ok": True, "queued": True})
            timeout_s = float(body.get("timeout_s") or WALK_TIMEOUT_S)
            result = svc.cat.rebuild(svc.fetch, svc.push, timeout_s=timeout_s)
            return self._send(200, {"ok": True, **result})

    return Handler


def serve(env: dict[str, str] | None = None) -> None:
    env = dict(os.environ if env is None else env)
    db = env.get("HUB_INDEX_DB") or str(DEFAULT_DB)
    cat = Catalogue(db)
    svc = Service(cat, env.get("HUB_WORKER_TOKEN", ""))
    if not svc.token:
        log.warning("HUB_WORKER_TOKEN is not set: /ingest and /rebuild will refuse every call")
    bind = env.get("HUB_INDEX_BIND", "0.0.0.0")
    port = int(env.get("HUB_INDEX_PORT", str(DEFAULT_PORT)))
    httpd = ThreadingHTTPServer((bind, port), make_handler(svc))
    threading.Thread(target=svc.loop, daemon=True, name="hub-index-loop").start()
    log.info("hub-index on %s:%s, db %s", bind, port, db)
    httpd.serve_forever()


def _local_url(path: str) -> str:
    port = int(os.environ.get("HUB_INDEX_PORT", str(DEFAULT_PORT)))
    return f"http://127.0.0.1:{port}{path}"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="hub_index.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    w = sub.add_parser("walk")
    w.add_argument("root")
    w.add_argument("start_rel")
    w.add_argument("state")
    rb = sub.add_parser("rebuild", help="ask the running service for a full rebuild (overnight step)")
    rb.add_argument("--timeout", type=float, default=WALK_TIMEOUT_S)
    rb.add_argument("--local", action="store_true", help="run in this process (service stopped)")
    rb.add_argument("--fresh", action="store_true", help="with --local: delete the catalogue first")
    sub.add_parser("health")
    s = sub.add_parser("search")
    s.add_argument("q")
    s.add_argument("--scope", default="items")
    args = ap.parse_args(argv)

    if args.cmd == "walk":
        return _walk_main(args.root, args.start_rel, args.state)
    if args.cmd == "serve":
        serve()
        return 0
    if args.cmd == "rebuild" and args.local:
        db = Path(os.environ.get("HUB_INDEX_DB") or DEFAULT_DB)
        if args.fresh:
            for suffix in ("", "-wal", "-shm"):
                Path(str(db) + suffix).unlink(missing_ok=True)
        cat = Catalogue(db)
        print(json.dumps(cat.rebuild(pi_fetch, pi_push_snapshot, timeout_s=args.timeout)))
        return 0
    try:
        if args.cmd == "rebuild":
            req = urllib.request.Request(
                _local_url("/rebuild"),
                data=json.dumps({"timeout_s": args.timeout}).encode(),
                method="POST",
                headers={"Content-Type": "application/json", "X-Worker-Token": os.environ.get("HUB_WORKER_TOKEN", "")},
            )
            timeout = args.timeout + 60
        elif args.cmd == "health":
            req, timeout = urllib.request.Request(_local_url("/health")), 30
        else:
            q = urllib.parse.urlencode({"q": args.q, "scope": args.scope})
            req, timeout = urllib.request.Request(_local_url(f"/search?{q}")), 30
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            print(resp.read().decode("utf-8"))
        return 0
    except urllib.error.HTTPError as exc:
        print(json.dumps({"ok": False, "error": f"HTTP {exc.code}"}))
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(json.dumps({"ok": False, "error": f"hub-index not reachable: {type(exc).__name__}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
