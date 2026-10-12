#!/usr/bin/env python3
"""Back-fill the Pi download journal from historic jobs (AP-5a.1).

Usage (on the Pi):
  python3 scripts/rebuild-download-index.py --from-jobs ~/homelab/data/hub-jobs --dry-run
  python3 scripts/rebuild-download-index.py --from-jobs ~/homelab/data/hub-jobs

Appends one minimal entry for every finished download job (``done``) that has no line in
``<jobs-dir>/download-index.jsonl`` yet. Append-only: nothing is rewritten or removed.
Housekeeping jobs (deletes, syncs, scans) are skipped. Prints a JSON summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))  # deployed copy lives beside the modules

from download_presets import segment_for_kind  # noqa: E402
from download_record import NOT_DOWNLOADS, load_records  # noqa: E402
from index_writer import append_entry, entry_from_job  # noqa: E402


def plan_from_jobs(jobs_dir: Path) -> tuple[list[dict], dict[str, int]]:
    journal = jobs_dir / "download-index.jsonl"
    known = {str(r.get("hub_job_id") or "") for r in load_records(journal).values()}
    todo: list[dict] = []
    counts = {"jobs": 0, "done": 0, "already_indexed": 0, "skipped_not_download": 0, "to_write": 0, "unreadable": 0}
    for path in sorted((jobs_dir / "jobs").glob("*.json")):
        counts["jobs"] += 1
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            counts["unreadable"] += 1
            continue
        if job.get("status") != "done":
            continue
        counts["done"] += 1
        kind = str(job.get("kind") or "").lower()
        if kind in NOT_DOWNLOADS:
            counts["skipped_not_download"] += 1
            continue
        if str(job.get("id") or "") in known:
            counts["already_indexed"] += 1
            continue
        entry = job.get("index_entry") if isinstance(job.get("index_entry"), dict) else entry_from_job(job)
        entry = dict(entry)
        entry.setdefault("segment", job.get("segment") or segment_for_kind(kind))
        entry["backfilled"] = True
        todo.append(entry)
    counts["to_write"] = len(todo)
    return todo, counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-jobs", required=True, type=Path, help="Hub JOBS_DIR (contains jobs/ and download-index.jsonl)")
    ap.add_argument("--dry-run", action="store_true", help="print counts, write nothing")
    args = ap.parse_args(argv)
    jobs_dir = args.from_jobs.expanduser()
    if not (jobs_dir / "jobs").is_dir():
        print(json.dumps({"error": f"no jobs/ under {jobs_dir}"}))
        return 2
    todo, counts = plan_from_jobs(jobs_dir)
    if not args.dry_run:
        for entry in todo:
            append_entry(jobs_dir / "download-index.jsonl", entry)
    counts["written"] = 0 if args.dry_run else len(todo)
    counts["dry_run"] = bool(args.dry_run)
    counts["by_kind"] = {}
    for e in todo:
        counts["by_kind"][e.get("kind")] = counts["by_kind"].get(e.get("kind"), 0) + 1
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
