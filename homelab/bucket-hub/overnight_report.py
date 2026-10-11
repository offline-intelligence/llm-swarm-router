"""Pure helpers for overnight run logs and last-night API (AP-2)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

DEFAULT_TZ = ZoneInfo("Australia/Brisbane")

LATEST_POINTER = "latest.json"


def run_file_for(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / f"{run_id}.jsonl"


def read_run_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def load_latest_run_id(runs_dir: Path) -> str | None:
    ptr = runs_dir / LATEST_POINTER
    if ptr.is_file():
        try:
            data = json.loads(ptr.read_text(encoding="utf-8"))
            rid = str(data.get("run_id") or "").strip()
            if rid:
                return rid
        except (OSError, json.JSONDecodeError):
            pass
    if not runs_dir.is_dir():
        return None
    candidates = sorted(p.stem for p in runs_dir.glob("*.jsonl"))
    return candidates[-1] if candidates else None


def list_run_summaries(runs_dir: Path, limit: int = 7) -> list[dict[str, str]]:
    if not runs_dir.is_dir():
        return []
    out: list[dict[str, str]] = []
    for path in sorted(runs_dir.glob("*.jsonl"), reverse=True):
        if len(out) >= limit:
            break
        lines = read_run_lines(path)
        steps = [_normalise_step_row(r) for r in lines]
        outcome = outcome_for(steps)
        out.append({"run_id": path.stem, "outcome": outcome})
    return out


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    text = str(ts).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def heartbeat_fresh(heartbeat_at: str | None, step_started_at: str) -> bool:
    hb = parse_iso(heartbeat_at)
    start = parse_iso(step_started_at)
    if hb is None or start is None:
        return False
    return hb > start


def outcome_for(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return "ok"
    critical_fail = any(not s.get("ok", True) and s.get("critical") for s in steps)
    if critical_fail:
        return "failed"
    any_fail = any(not s.get("ok", True) for s in steps)
    if any_fail:
        return "attention"
    return "ok"


def jobs_in_window(
    jobs: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for job in jobs:
        fin = parse_iso(job.get("finished_at"))
        if fin is None:
            continue
        if start <= fin < end:
            out.append(job)
    return out


def humanise_error_text(error: Any) -> str:
    if error is None:
        return ""
    text = str(error).strip()
    if not text:
        return ""
    low = text.lower()
    if "no peers" in low or "dead torrent" in low:
        return "no seeders"
    if len(text) > 120:
        return text[:117] + "..."
    return text


def _normalise_step_row(row: dict[str, Any]) -> dict[str, Any]:
    critical = bool(row.get("critical"))
    ok = bool(row.get("ok", True))
    took = row.get("took_s")
    if took is None:
        took = row.get("duration_s")
    started = row.get("step_started_at") or row.get("at")
    return {
        "label": row.get("label") or row.get("type") or "?",
        "critical": critical,
        "ok": ok,
        "result_text": row.get("result_text") or _default_result_text(row),
        "started_at": started,
        "took_s": took,
        "type": row.get("type"),
        "target": row.get("target"),
        "timed_out": bool(row.get("timed_out") or (row.get("result") or {}).get("timed_out")),
        "error": row.get("error"),
        "warnings": list(row.get("warnings") or []),
    }


def _default_result_text(row: dict[str, Any]) -> str:
    if row.get("error"):
        return str(row["error"])
    res = row.get("result") or {}
    if res.get("timed_out"):
        limit = row.get("timeout_min") or res.get("timeout_min")
        if limit:
            return f"Stopped after {int(limit)} m limit"
        return "Stopped after time limit"
    if row.get("ok"):
        return "OK"
    return "Failed"


def _run_bounds(lines: list[dict[str, Any]]) -> tuple[datetime | None, datetime | None]:
    starts: list[datetime] = []
    ends: list[datetime] = []
    for row in lines:
        for key in ("step_started_at", "at"):
            ts = parse_iso(row.get(key))
            if ts:
                starts.append(ts)
                break
        for key in ("step_finished_at", "finished_at"):
            ts = parse_iso(row.get(key))
            if ts:
                ends.append(ts)
        if not ends:
            ts = parse_iso(row.get("at"))
            if ts:
                ends.append(ts)
    if not starts and lines:
        ts = parse_iso(lines[0].get("at"))
        if ts:
            starts.append(ts)
    if not ends and lines:
        ts = parse_iso(lines[-1].get("at"))
        if ts:
            ends.append(ts)
    start = min(starts) if starts else None
    end = max(ends) if ends else None
    return start, end


def _jobs_block(
    jobs: list[dict[str, Any]],
    start: datetime | None,
    end: datetime | None,
) -> dict[str, Any]:
    if start is None or end is None:
        return {
            "finished": 0,
            "failed": 0,
            "still_queued": 0,
            "first_failure": None,
        }
    in_win = jobs_in_window(jobs, start, end)
    finished = sum(1 for j in in_win if j.get("status") == "done")
    failed_jobs = [j for j in in_win if j.get("status") == "error"]
    failed = len(failed_jobs)
    still = sum(
        1
        for j in jobs
        if j.get("status") in ("queued", "running", "claimed", "paused")
    )
    first_failure = None
    if failed_jobs:
        failed_jobs.sort(key=lambda j: j.get("finished_at") or "")
        j0 = failed_jobs[0]
        first_failure = {
            "title": j0.get("title") or j0.get("kind") or "?",
            "error": humanise_error_text(j0.get("error") or j0.get("error_display")),
        }
    return {
        "finished": finished,
        "failed": failed,
        "still_queued": still,
        "first_failure": first_failure,
    }


def _step_summary_line(steps: list[dict[str, Any]]) -> str:
    ran = len(steps)
    ok_n = sum(1 for s in steps if s.get("ok"))
    parts: list[str] = [f"{ok_n} of {ran} steps ran"]
    for s in steps:
        if s.get("ok"):
            continue
        label = s.get("label") or "Step"
        if s.get("critical"):
            parts.append(f"{label} failed")
        else:
            parts.append(f"{label} did not complete (not required)")
    return " · ".join(parts[:3])


def _format_window_line(start: datetime | None, end: datetime | None, tz: ZoneInfo) -> str:
    if start is None or end is None:
        return "No run recorded last night"
    s = start.astimezone(tz)
    e = end.astimezone(tz)
    day = f"{s.strftime('%a')} {s.day} {s.strftime('%b')}"
    return f"{day}, {s.strftime('%H:%M')}–{e.strftime('%H:%M')}"


def next_run_at_from_schedule(
    schedule: dict[str, Any],
    now: datetime,
    tz: ZoneInfo = DEFAULT_TZ,
) -> str | None:
    window = schedule.get("window") or {}
    start_hm = str(window.get("start") or "22:00")
    m = re.match(r"(\d{1,2}):(\d{2})", start_hm)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    local = now.astimezone(tz)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def enabled_step_limits_min(schedule: dict[str, Any]) -> tuple[int, int, int]:
    steps = schedule.get("steps") or []
    enabled = [s for s in steps if s.get("enabled", True)]
    disabled = [s for s in steps if not s.get("enabled", True)]
    total = sum(int(s.get("timeout_min") or s.get("duration_min") or 5) for s in enabled)
    window = schedule.get("window") or {}
    start = parse_hm(str(window.get("start") or "22:00"))
    end = parse_hm(str(window.get("end") or "06:00"))
    span = end - start
    if span <= 0:
        span += 24 * 60
    return total, span, len(disabled)


def parse_hm(hm: str) -> int:
    m = re.match(r"(\d{1,2}):(\d{2})", hm)
    if not m:
        return 0
    return int(m.group(1)) * 60 + int(m.group(2))


def warnings_from_run_lines(lines: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for row in lines:
        for w in row.get("warnings") or []:
            if w and w not in out:
                out.append(str(w))
        res = row.get("result") or {}
        for w in res.get("warnings") or []:
            if w and w not in out:
                out.append(str(w))
    return out


def build_last_night(
    run_lines: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    schedule: dict[str, Any],
    now: datetime,
    *,
    run_id: str | None = None,
    worker_state: str | None = None,
    tz: ZoneInfo = DEFAULT_TZ,
) -> dict[str, Any]:
    steps = [_normalise_step_row(r) for r in run_lines]
    start, end = _run_bounds(run_lines)
    outcome = outcome_for(steps)
    jobs_block = _jobs_block(jobs, start, end)
    started_at = start.isoformat() if start else None
    finished_at = end.isoformat() if end else None
    window_line = _format_window_line(start, end, tz)
    summary_line = _step_summary_line(steps) if steps else "No run recorded last night"
    next_run = next_run_at_from_schedule(schedule, now, tz)
    warnings = warnings_from_run_lines(run_lines)

    downloads_line = ""
    if jobs_block["finished"] or jobs_block["failed"]:
        downloads_line = (
            f"Downloads: {jobs_block['finished']} finished"
            f"{', ' + str(jobs_block['failed']) + ' failed' if jobs_block['failed'] else ''}"
        )
        ff = jobs_block.get("first_failure")
        if ff and ff.get("title"):
            err = ff.get("error") or "failed"
            downloads_line += f' — "{ff["title"]}" ({err})'

    card_lines = [
        window_line,
        summary_line,
        downloads_line or "Downloads: none in this run window",
        f"Next run: {next_run_at_display(next_run, tz)} · {worker_state or 'worker unknown'}",
    ]

    legacy_run = {
        "status": "done" if outcome == "ok" else outcome,
        "started_at": started_at,
        "finished_at": finished_at,
        "date": start.astimezone(tz).strftime("%Y-%m-%d") if start else None,
        "steps_total": len(steps),
        "steps_ok": sum(1 for s in steps if s.get("ok")),
    }

    return {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "outcome": outcome,
        "steps": steps,
        "jobs": jobs_block,
        "next_run_at": next_run,
        "worker_state": worker_state,
        "warnings": warnings,
        "card_lines": card_lines,
        "message": "No run recorded last night" if not steps else None,
        "run": legacy_run,
    }


def next_run_at_display(iso: str | None, tz: ZoneInfo = DEFAULT_TZ) -> str:
    if not iso:
        return "not scheduled"
    dt = parse_iso(iso)
    if not dt:
        return "not scheduled"
    local = dt.astimezone(tz)
    return f"tonight {local.strftime('%H:%M')}"


def evaluate_machine_wake(
    step: dict[str, Any],
    step_started_at: str,
    heartbeat_at: str | None,
    *,
    ping_ok: bool | None = None,
) -> tuple[bool, str]:
    target = str(step.get("target") or "ubuntu").lower()
    timeout_min = int(step.get("timeout_min") or step.get("duration_min") or 5)
    if target in ("ubuntu", "ai-server"):
        if heartbeat_fresh(heartbeat_at, step_started_at):
            return True, f"Awake (heartbeat { _hb_short(heartbeat_at, step_started_at) })"
        return False, f"Stopped after {timeout_min} m limit"
    if target == "tnas":
        if ping_ok:
            return True, "Awake"
        if ping_ok is False:
            return False, "Did not respond (not required)"
        return False, "Did not respond (not required)"
    return bool(heartbeat_fresh(heartbeat_at, step_started_at)), "Wake check"


def _hb_short(heartbeat_at: str | None, step_started_at: str) -> str:
    hb = parse_iso(heartbeat_at)
    if hb is None:
        return "unknown"
    return hb.astimezone(DEFAULT_TZ).strftime("%H:%M")


def evaluate_mount_check(step_started_at: str, heartbeat_at: str | None) -> tuple[bool, str]:
    if heartbeat_fresh(heartbeat_at, step_started_at):
        return True, "Drives ready"
    return False, "Worker heartbeat stale"


def queue_drain_counts(
    jobs: list[dict[str, Any]],
    step_started_at: str,
    step_finished_at: str,
) -> dict[str, int]:
    start = parse_iso(step_started_at)
    end = parse_iso(step_finished_at)
    if start is None or end is None:
        return {"finished": 0, "failed": 0, "still_queued": 0}
    in_win = jobs_in_window(jobs, start, end)
    finished = sum(1 for j in in_win if j.get("status") == "done")
    failed = sum(1 for j in in_win if j.get("status") == "error")
    still = sum(
        1
        for j in jobs
        if j.get("status") in ("queued", "running", "claimed", "paused")
    )
    return {"finished": finished, "failed": failed, "still_queued": still}


def machine_wake_poll(
    deadline: float,
    interval: float,
    fetch_heartbeat: Callable[[], str | None],
    step_started_at: str,
) -> tuple[bool, str | None]:
    import time

    while time.time() < deadline:
        hb = fetch_heartbeat()
        if heartbeat_fresh(hb, step_started_at):
            return True, hb
        time.sleep(interval)
    return False, fetch_heartbeat()
