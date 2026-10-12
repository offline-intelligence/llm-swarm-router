"""Per-download record (AP-5a.1): the person view and the machine view of every download.

The journal (``download-index.jsonl``, append-only, written through
``index_writer.append_entry``) stays the truth. This module reads it as a merged view and
adds three kinds of line besides the normal entry:

- ``{"event": "deleted", "entry_id", ...}``: a tombstone after a Hub delete; the entry
  keeps its data and gets ``status: "deleted"``.
- ``{"event": "note", "entry_id", "user_note"}``: a "Why I kept this" edit.
- anything else: a full entry, last line wins for the same ``entry_id``.

Shared by the Pi (``app.py``) and the worker (``ABOUT-THIS-DOWNLOAD.md`` beside folder
downloads). Stdlib only.
"""
from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from index_writer import SCHEMA_VERSION, scrub_free_text, secret_scan

log = logging.getLogger("bucket-hub.download_record")

ABOUT_FILENAME = "ABOUT-THIS-DOWNLOAD.md"

# Job kinds that are housekeeping, not downloads: never get their own index entry.
# "minecraft": Minecraft-server jobs (2 seen in the 2026-10-12 back-fill dry run), not downloads.
NOT_DOWNLOADS = frozenset(
    {"storage_delete", "sync", "storage_scan", "github_stars_sync", "huggingface_likes_sync", "minecraft"}
)

REPO_KINDS = frozenset({"github_repo", "github_release", "huggingface_repo"})

# Search weights (spec A6): title/full name 3, tags/topics 2, description/note 1.5, excerpt 1.
_WEIGHTED_FIELDS: tuple[tuple[str, float], ...] = (
    ("full_name", 3.0),
    ("title", 3.0),
    ("repo_id", 3.0),
    ("release_name", 3.0),
    ("show_title", 3.0),
    ("hub_tags", 2.0),
    ("topics", 2.0),
    ("pipeline_tag", 2.0),
    ("library_name", 2.0),
    ("description", 1.5),
    ("user_note", 1.5),
    ("context", 1.5),
    ("readme_excerpt", 1.0),
    ("rel_path", 1.0),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tombstone(entry_id: str, *, job_id: str = "", paths: Iterable[str] = (), by: str = "hub") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event": "deleted",
        "entry_id": entry_id,
        "job_id": job_id or None,
        "paths": [str(p) for p in paths],
        "by": by,
        "at": _now(),
    }


def note_event(entry_id: str, user_note: str) -> dict[str, Any]:
    line = {
        "schema_version": SCHEMA_VERSION,
        "event": "note",
        "entry_id": entry_id,
        "user_note": scrub_free_text(user_note),
        "at": _now(),
    }
    secret_scan(line)
    return line


def _apply(out: dict[str, dict[str, Any]], row: dict[str, Any], line_no: int) -> None:
    eid = str(row.get("entry_id") or f"line-{line_no}")
    event = row.get("event")
    prev = out.get(eid)
    if event == "deleted":
        if prev is None:
            return  # nothing known to delete
        merged = dict(prev)
        merged["status"] = "deleted"
        merged["deleted_at"] = row.get("at")
        merged["deleted_by"] = row.get("by")
        merged["deleted_paths"] = row.get("paths") or []
        out[eid] = merged
    elif event == "note":
        if prev is None:
            return
        merged = dict(prev)
        merged["user_note"] = row.get("user_note")
        merged["note_updated_at"] = row.get("at")
        out[eid] = merged
    else:
        out[eid] = row


def iter_lines(path: Path, start: int = 0) -> Iterable[tuple[int, int, dict[str, Any]]]:
    """``(line_no, end_offset, row)`` for each valid JSON object line from byte ``start``."""
    if not path.is_file():
        return
    with path.open("rb") as fh:
        fh.seek(start)
        line_no = 0
        while True:
            raw = fh.readline()
            if not raw:
                break
            line_no += 1
            end = fh.tell()
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                log.warning("skipping corrupt journal line at byte %s in %s", end, path)
                continue
            if isinstance(row, dict):
                yield line_no, end, row


def load_records(path: str | Path) -> dict[str, dict[str, Any]]:
    """Merged view of the journal: one record per ``entry_id``, events applied in order."""
    out: dict[str, dict[str, Any]] = {}
    for line_no, _end, row in iter_lines(Path(path)):
        _apply(out, row, line_no)
    return out


def export_since(path: str | Path, since: int = 0, *, kind: str = "") -> tuple[list[dict[str, Any]], int]:
    """Records touched after byte offset ``since`` (merged with earlier lines) and the new cursor.

    The cursor is the journal size in bytes; the journal is append-only, so a client that
    stores it gets exactly the records that changed since.
    """
    p = Path(path)
    size = p.stat().st_size if p.is_file() else 0
    since = max(0, min(int(since or 0), size))
    touched: list[str] = []
    for _n, _end, row in iter_lines(p, since):
        eid = row.get("entry_id")
        if eid and eid not in touched:
            touched.append(str(eid))
    if not touched:
        return [], size
    records = load_records(p)
    rows = [records[e] for e in touched if e in records]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    for r in rows:
        secret_scan(r)
    return rows, size


def sources(records: dict[str, dict[str, Any]], kind: str = "") -> list[str]:
    """``source_id`` of every record that is not failed or deleted (sync diffing)."""
    out = {
        str(r.get("source_id"))
        for r in records.values()
        if r.get("source_id")
        and r.get("status") not in ("failed", "deleted")
        and (not kind or r.get("kind") == kind)
    }
    return sorted(out)


def _field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value)
    return str(value)


def search(
    records: dict[str, dict[str, Any]],
    q: str = "",
    *,
    kind: str = "",
    segment: str = "",
    status: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Spec A6 substring search: every term must match some field; weighted score.

    Deleted records only appear when ``status == "deleted"``; failed ones only when asked.
    """
    terms = [t.lower() for t in (q or "").split() if t.strip()]
    hits: list[tuple[float, str, dict[str, Any]]] = []
    for rec in records.values():
        st = str(rec.get("status") or "")
        if status:
            if st != status:
                continue
        elif st in ("deleted", "failed"):
            continue
        if kind and rec.get("kind") != kind:
            continue
        if segment and rec.get("segment") != segment:
            continue
        score = 0.0
        ok = True
        texts = [(_field_text(rec.get(f)).lower(), w) for f, w in _WEIGHTED_FIELDS]
        for term in terms:
            best = max((w for text, w in texts if term in text), default=0.0)
            if not best:
                ok = False
                break
            score += best
        if ok:
            hits.append((score, str(rec.get("downloaded_at") or ""), rec))
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    page = hits[max(0, offset) : max(0, offset) + max(1, min(limit, 200))]
    return {"total": len(hits), "items": [dict(h[2], score=h[0]) for h in page]}


def entry_paths(entry: dict[str, Any], archive_root: str = "") -> list[str]:
    """Absolute paths a record occupies, for matching a delete."""
    out: list[str] = []
    local = str(entry.get("local_path") or "").rstrip("/")
    rel = str(entry.get("rel_path") or "").strip("/")
    if local:
        out.append(local)
        if rel and not rel.startswith("/"):
            out.append(f"{local}/{rel}")
    if rel and entry.get("kind") in REPO_KINDS and archive_root:
        out.append(f"{archive_root.rstrip('/')}/{rel}")
    if rel.startswith("/"):
        out.append(rel)
    return [p for p in dict.fromkeys(out) if p]


def entries_under(records: dict[str, dict[str, Any]], deleted_path: str, archive_root: str = "") -> list[str]:
    """``entry_id``s whose own folder is ``deleted_path`` or inside it (not its parent).

    A record whose only path is a shared destination folder (e.g. ``/mnt/tnas/inbox``)
    is matched only when that exact folder is deleted.
    """
    target = str(deleted_path).rstrip("/")
    hit: list[str] = []
    for eid, rec in records.items():
        if rec.get("status") == "deleted":
            continue
        paths = entry_paths(rec, archive_root)
        if not paths:
            continue
        own = paths[-1]  # most specific path
        if own == target or own.startswith(target + "/"):
            hit.append(eid)
    return hit


def _human_size(n: Any) -> str:
    try:
        size = float(n)
    except (TypeError, ValueError):
        return "unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "unknown"


def context_card(entry: dict[str, Any]) -> str:
    """Markdown for people and agents: What / Where / Why / When, then key metadata."""
    title = entry.get("full_name") or entry.get("title") or entry.get("repo_id") or entry.get("entry_id")
    kind = entry.get("kind") or "download"
    lines = [f"# {title}", ""]
    lines += ["## What", ""]
    lines.append(f"- Type: {kind}" + (f" ({entry['segment']})" if entry.get("segment") else ""))
    for label, key in (("Description", "description"), ("Pipeline", "pipeline_tag"), ("Media", "media_type")):
        if entry.get(key):
            lines.append(f"- {label}: {scrub_free_text(str(entry[key]))}")
    if entry.get("topics"):
        lines.append(f"- Topics: {', '.join(str(t) for t in entry['topics'])}")
    if entry.get("hub_tags"):
        lines.append(f"- Hub tags: {', '.join(str(t) for t in entry['hub_tags'])}")
    lines += ["", "## Where", ""]
    for label, key in (("Saved to", "saves_to"), ("Drive", "drive_id"), ("Folder", "local_path"), ("Path", "rel_path"), ("Library", "library_path")):
        if entry.get(key):
            lines.append(f"- {label}: {entry[key]}")
    lines.append(f"- Status: {entry.get('status') or 'done'}")
    lines += ["", "## Why", ""]
    lines.append(f"- Source: {entry.get('source') or 'manual'}")
    if entry.get("source_url"):
        lines.append(f"- From: {entry['source_url']}")
    if entry.get("context"):
        lines.append(f"- Context: {scrub_free_text(str(entry['context']))}")
    lines.append(f"- Why I kept this: {scrub_free_text(str(entry.get('user_note') or '')) or '(no note yet)'}")
    lines += ["", "## When", ""]
    lines.append(f"- Downloaded: {entry.get('downloaded_at') or 'unknown'}")
    if entry.get("deleted_at"):
        lines.append(f"- Deleted: {entry['deleted_at']} by {entry.get('deleted_by') or 'hub'}")
    lines.append(f"- Size: {_human_size(entry.get('size_bytes'))}")
    fs = entry.get("file_summary")
    if isinstance(fs, dict) and fs.get("count"):
        lines.append(f"- Files: {fs.get('count')}")
    if entry.get("licence_accepted_by") or entry.get("license") or entry.get("license_spdx"):
        lines.append(f"- Licence: {entry.get('license') or entry.get('license_spdx') or 'gated'}"
                     + (" (accepted by you)" if entry.get("licence_accepted_by") else ""))
    excerpt = entry.get("readme_excerpt")
    if excerpt:
        lines += ["", "## README excerpt", "", scrub_free_text(str(excerpt)) or ""]
    lines += ["", f"<!-- entry_id: {entry.get('entry_id')} · schema {entry.get('schema_version') or SCHEMA_VERSION} -->", ""]
    text = "\n".join(lines)
    secret_scan({"card": text})
    return text


def write_about_file(folder: Path, entry: dict[str, Any]) -> Path:
    """``ABOUT-THIS-DOWNLOAD.md`` beside a folder download (the person view on disk)."""
    path = Path(folder) / ABOUT_FILENAME
    path.write_text(context_card(entry), encoding="utf-8")
    return path


def count_snapshot_bytes(data: bytes, max_lines: int = 2_000_000) -> int:
    """Validate an AP-5a.2 snapshot (gzip JSONL of objects with ``entry_id``); return its size."""
    try:
        text = gzip.decompress(data).decode("utf-8")
    except (OSError, EOFError, UnicodeDecodeError) as exc:
        raise ValueError(f"not a gzip JSONL snapshot: {type(exc).__name__}") from exc
    n = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"bad JSON on snapshot line {n + 1}") from exc
        if not isinstance(row, dict) or not row.get("entry_id"):
            raise ValueError(f"snapshot line {n + 1} has no entry_id")
        n += 1
        if n > max_lines:
            raise ValueError("snapshot too long")
    return n


def load_snapshot(path: str | Path) -> dict[str, dict[str, Any]]:
    """Records from the catalogue snapshot (AP-5b fallback search reads this with ``search``)."""
    p = Path(path)
    if not p.is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("entry_id"):
                out[str(row["entry_id"])] = row
    return out
