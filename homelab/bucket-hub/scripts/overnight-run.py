#!/usr/bin/env python3
"""Execute Bucket-HUB overnight schedule (complete-or-timeout per step)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_HUB_ROOT = Path(__file__).resolve().parents[1]
if str(_HUB_ROOT) not in sys.path:
    sys.path.insert(0, str(_HUB_ROOT))

from overnight_report import (  # noqa: E402
    evaluate_machine_wake,
    evaluate_mount_check,
    heartbeat_fresh,
    machine_wake_poll,
    queue_drain_counts,
    run_file_for,
)

HUB_BASE = os.environ.get("HUB_BASE", "http://127.0.0.1:3020").rstrip("/")
JOBS_DIR = Path(os.environ.get("JOBS_DIR", os.path.expanduser("~/homelab/data/hub-jobs")))
SCHEDULE_FILE = JOBS_DIR / "overnight-schedule.json"
RUNS_DIR = JOBS_DIR / "overnight-runs"
STATE_FILE = JOBS_DIR / "overnight-run-state.json"
TZ = ZoneInfo(os.environ.get("HUB_TZ", "Australia/Brisbane"))
UBUNTU_SSH = os.environ.get("OVERNIGHT_UBUNTU_SSH", "bucket@192.168.50.65")
# The timer runs with only HUB_BASE/JOBS_DIR/HUB_TZ set, so fall back to the key the Hub
# itself uses for ai-server (machines + vLLM controls) when MACHINES_SSH_IDENTITY is unset.
SSH_IDENTITY = os.environ.get("MACHINES_SSH_IDENTITY", "").strip() or (
    str(JOBS_DIR / "machines_ssh") if (JOBS_DIR / "machines_ssh").is_file() else ""
)
DSH_SCRIPT = os.environ.get("OVERNIGHT_DSH_SCRIPT", "~/homelab/scripts/overnight-dsh-task.sh")
# AP-5a.2: the catalogue rebuild runs on ai-server with the worker env (token, HUB_URL).
INDEX_REBUILD_CMD = os.environ.get(
    "OVERNIGHT_INDEX_REBUILD_CMD",
    "set -a; . ~/homelab/scripts/hub-worker.env; set +a; python3 ~/homelab/scripts/hub_index.py rebuild --timeout {timeout_s}",
)


def log(msg: str) -> None:
    print(f"[overnight-run] {msg}", flush=True)


def write_state(state: dict[str, Any]) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def hub_json(method: str, path: str, body: dict | None = None, timeout: float = 600.0) -> dict:
    url = f"{HUB_BASE}{path}"
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _worker_heartbeat_at() -> str | None:
    try:
        st = hub_json("GET", "/api/status", timeout=30.0)
    except Exception:
        return None
    w = st.get("worker") or {}
    return w.get("heartbeat_at") or st.get("heartbeat_at")


def write_latest(run_id: str) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / "latest.json").write_text(
        json.dumps({"run_id": run_id}) + "\n", encoding="utf-8"
    )


def append_run(entry: dict, run_id: str) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = run_file_for(RUNS_DIR, run_id)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def load_schedule() -> dict:
    if SCHEDULE_FILE.is_file():
        return json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
    default = Path(__file__).with_name("overnight-schedule.default.json")
    if default.is_file():
        return json.loads(default.read_text(encoding="utf-8"))
    raise SystemExit(f"No schedule at {SCHEDULE_FILE}")


def step_timeout_min(step: dict) -> int:
    return int(step.get("timeout_min") or step.get("duration_min") or 5)


def ssh_ubuntu(cmd: str, timeout: float = 600.0) -> tuple[int, str]:
    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=12",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if SSH_IDENTITY:
        args.extend(["-i", SSH_IDENTITY])
    args.append(UBUNTU_SSH)
    args.append(cmd)
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    out = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, out


def poll_until(
    deadline: float,
    interval: float,
    check,
) -> tuple[bool, Any]:
    """Return (completed, result) when check() is truthy, or (False, None) at deadline."""
    while time.time() < deadline:
        result = check()
        if result:
            return True, result
        time.sleep(interval)
    return False, None


def run_step_body(step: dict) -> dict:
    stype = step.get("type") or ""

    if stype == "machine_wake":
        mid = step.get("target") or "tnas"
        return hub_json("POST", f"/api/machines/{mid}/wake")
    if stype == "machine_sleep":
        mid = step.get("target") or "ubuntu"
        return hub_json("POST", f"/api/machines/{mid}/sleep")
    if stype == "mount_check":
        st = hub_json("GET", "/api/status")
        w = st.get("worker") or {}
        if not w.get("media_mounted"):
            raise RuntimeError("Media HDD not mounted on worker")
        return {"ok": True, "worker": w}
    if stype == "llm_start":
        return hub_json("POST", "/api/llm/start", timeout=720.0)
    if stype == "llm_stop":
        return hub_json("POST", "/api/llm/stop", timeout=180.0)
    if stype in ("research_synthesis", "dsh_research"):
        hub_json("POST", "/api/research", {"preset": "ai_ml"})
        return {"ok": True, "research_queued": True}
    if stype in ("log_review", "dsh_log_review"):
        jobs = hub_json("GET", "/api/jobs/summary/last-night")
        path = Path.home() / "homelab/data/logs/overnight-log-input.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        return {"ok": True, "input": str(path)}
    if stype == "sync_job":
        log("seedvault sync disabled unless configured")
        return {"ok": True, "skipped": True}
    if stype == "queue_drain":
        try:
            jobs_data = hub_json("GET", "/api/jobs?limit=50")
            all_jobs = jobs_data if isinstance(jobs_data, list) else jobs_data.get("jobs") or []
        except Exception:
            all_jobs = []
        active = [
            j
            for j in all_jobs
            if j.get("status") in ("queued", "running", "claimed")
        ]
        log(f"Queue drain: {len(active)} active jobs to process (paused jobs do not block)")
        return {"ok": True, "active": len(active), "total_jobs": len(all_jobs)}
    if stype == "index_rebuild":
        return run_index_rebuild(step)
    if stype == "storage_scan":
        hub_json("POST", "/api/storage/scan", {"volume": "all"})
        return {"ok": True}
    raise RuntimeError(f"Unknown step type: {stype}")


def run_index_rebuild(step: dict) -> dict:
    """Ask hub-index on ai-server for a full rebuild; returns its counts."""
    budget_s = step_timeout_min(step) * 60
    walk_s = max(60, budget_s - 60)  # leave a minute for the snapshot push and ssh
    rc, out = ssh_ubuntu(INDEX_REBUILD_CMD.format(timeout_s=walk_s), timeout=budget_s)
    try:
        data = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except (json.JSONDecodeError, IndexError):
        data = {}
    if rc != 0 or not data.get("ok"):
        raise RuntimeError(f"index rebuild failed (rc {rc}): {(data.get('error') or out)[-200:]}")
    keep = ("new", "changed", "missing", "deleted", "items", "files", "secs", "snapshot")
    return {"ok": True, **{k: data.get(k) for k in keep if k in data}}


def index_rebuild_text(result: dict) -> str:
    counts = ", ".join(f"{int(result.get(k) or 0)} {k}" for k in ("new", "changed", "missing", "deleted"))
    snap = result.get("snapshot") or {}
    return counts + ("" if snap.get("pushed") else "; Pi snapshot not pushed")


def run_step_poll(step: dict, deadline: float) -> dict:
    """Poll for completion after run_step_body kick-off; returns when done or raises on hard fail."""
    stype = step.get("type") or ""

    if stype in ("research_synthesis", "dsh_research"):
        def check_research():
            try:
                data = hub_json("GET", "/api/research?preset=ai_ml")
                if data.get("results"):
                    return data
            except urllib.error.HTTPError:
                pass
            return None

        done, data = poll_until(deadline, 5.0, check_research)
        if not done:
            return {"ok": True, "timed_out": True, "note": "research fetch incomplete"}
        # DeepSeek headless synthesis on Ubuntu
        ctx_path = Path.home() / "homelab/data/logs/overnight-research-context.json"
        ctx_path.parent.mkdir(parents=True, exist_ok=True)
        ctx_path.write_text(json.dumps(data, indent=2)[:120000], encoding="utf-8")
        remain = max(30, int(deadline - time.time()))
        rc, out = ssh_ubuntu(
            f"bash {DSH_SCRIPT} research {remain} ~/homelab/data/logs/overnight-research.md {ctx_path}",
            timeout=remain + 30,
        )
        return {
            "ok": rc in (0, 124),
            "research_count": len(data.get("results") or []),
            "dsh_rc": rc,
            "dsh_out_tail": out[-500:],
            "timed_out": rc == 124,
        }

    if stype in ("log_review", "dsh_log_review"):
        remain = max(30, int(deadline - time.time()))
        in_path = Path.home() / "homelab/data/logs/overnight-log-input.json"
        rc, out = ssh_ubuntu(
            f"bash {DSH_SCRIPT} logs {remain} ~/homelab/data/logs/overnight-log-review.md {in_path}",
            timeout=remain + 30,
        )
        return {"ok": rc in (0, 124), "dsh_rc": rc, "dsh_out_tail": out[-500:], "timed_out": rc == 124}

    if stype == "queue_drain":
        completed_count = 0
        last_log = 0.0

        def check_queue():
            nonlocal completed_count, last_log
            try:
                jobs_data = hub_json("GET", "/api/jobs?limit=50")
                all_jobs = jobs_data if isinstance(jobs_data, list) else jobs_data.get("jobs") or []
            except Exception:
                return None
            active = [
                j
                for j in all_jobs
                if j.get("status") in ("queued", "running", "claimed")
            ]
            done_jobs = [j for j in all_jobs if j.get("status") in ("done", "error")]
            completed_count = len(done_jobs)
            now = time.time()
            if now - last_log >= 60:
                log(f"  drain poll: {len(active)} active, {completed_count} done/error")
                last_log = now
            if not active:
                return {"active": 0, "completed": completed_count}
            return None

        done, result = poll_until(deadline, 15.0, check_queue)
        if done and result:
            result["ok"] = True
            result["timed_out"] = False
            return result
        return {"ok": True, "timed_out": True, "active": "unknown", "completed": completed_count}

    return {"ok": True}


def _finish_step_entry(
    step: dict,
    step_started: str,
    result: dict,
    *,
    ok: bool,
    result_text: str,
) -> dict[str, Any]:
    finished = datetime.now(timezone.utc).isoformat()
    out = {
        "ok": ok,
        "result_text": result_text,
        "step_started_at": step_started,
        "step_finished_at": finished,
        "result": result,
        "timed_out": bool(result.get("timed_out")),
    }
    if step.get("type") == "queue_drain":
        try:
            jobs_data = hub_json("GET", "/api/jobs?limit=200", timeout=60.0)
            all_jobs = jobs_data if isinstance(jobs_data, list) else jobs_data.get("jobs") or []
            counts = queue_drain_counts(all_jobs, step_started, finished)
            out["result"] = {**result, **counts}
            out["result_text"] = (
                f"{counts['finished']} finished, {counts['failed']} failed"
                f"{', ' + str(counts['still_queued']) + ' still queued' if counts['still_queued'] else ''}"
            )
        except Exception:
            pass
    return out


def run_step(step: dict, dry_run: bool, step_started: str) -> dict:
    label = step.get("label") or step.get("type")
    timeout_s = step_timeout_min(step) * 60
    log(
        f"{'[dry-run] ' if dry_run else ''}{label} "
        f"(max {step_timeout_min(step)} m, advance when done or timeout)"
    )
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "timeout_min": step_timeout_min(step),
            "result_text": "Dry run",
            "step_started_at": step_started,
            "step_finished_at": datetime.now(timezone.utc).isoformat(),
        }

    deadline = time.time() + timeout_s
    t0 = time.time()
    stype = step.get("type") or ""

    if stype == "machine_wake":
        target = str(step.get("target") or "ubuntu").lower()
        try:
            run_step_body(step)
        except Exception as exc:
            raise
        if target in ("ubuntu", "ai-server"):
            ok_poll, hb = machine_wake_poll(
                deadline,
                5.0,
                _worker_heartbeat_at,
                step_started,
            )
            ok, text = evaluate_machine_wake(step, step_started, hb)
            return _finish_step_entry(
                step,
                step_started,
                {"heartbeat_at": hb, "timed_out": not ok_poll},
                ok=ok,
                result_text=text,
            )
        ok_ping = True
        ok, text = evaluate_machine_wake(step, step_started, None, ping_ok=ok_ping)
        return _finish_step_entry(
            step,
            step_started,
            {"ping_ok": ok_ping},
            ok=ok,
            result_text=text,
        )

    result_holder: dict[str, Any] = {}
    error_holder: list[Exception] = []

    def worker() -> None:
        try:
            result_holder["result"] = run_step_body(step)
        except Exception as exc:
            error_holder.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=max(1.0, deadline - time.time()))

    if error_holder:
        raise error_holder[0]
    if thread.is_alive():
        # Body still running — poll path for long steps or mark timeout
        stype = step.get("type") or ""
        if stype in ("dsh_research", "research_synthesis", "dsh_log_review", "log_review", "queue_drain"):
            poll_result = run_step_poll(step, deadline)
            elapsed = round(time.time() - t0, 1)
            poll_result["elapsed_s"] = elapsed
            poll_result["advance_reason"] = "timeout" if poll_result.get("timed_out") else "complete"
            return poll_result
        log(f"Step exceeded timeout ({timeout_s}s) — advancing")
        return {"ok": True, "timed_out": True, "elapsed_s": round(time.time() - t0, 1)}

    elapsed = round(time.time() - t0, 1)
    base = result_holder.get("result") or {"ok": True}
    if stype == "mount_check":
        hb = _worker_heartbeat_at()
        ok, text = evaluate_mount_check(step_started, hb)
        if not ok:
            raise RuntimeError(text)
        return _finish_step_entry(step, step_started, {"heartbeat_at": hb}, ok=True, result_text=text)
    if stype in ("dsh_research", "research_synthesis", "dsh_log_review", "log_review", "queue_drain"):
        poll_result = run_step_poll(step, deadline)
        poll_result["elapsed_s"] = elapsed
        poll_result["advance_reason"] = "timeout" if poll_result.get("timed_out") else "complete"
        ok = bool(poll_result.get("ok", True))
        text = (
            f"Stopped after {step_timeout_min(step)} m limit"
            if poll_result.get("timed_out")
            else "Complete"
        )
        merged = _finish_step_entry(step, step_started, poll_result, ok=ok, result_text=text)
        merged["elapsed_s"] = elapsed
        merged["advance_reason"] = poll_result.get("advance_reason")
        return merged
    base["elapsed_s"] = elapsed
    base["advance_reason"] = "complete"
    return _finish_step_entry(
        step,
        step_started,
        base,
        ok=True,
        result_text=index_rebuild_text(base) if stype == "index_rebuild" else "OK",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    schedule = load_schedule()
    steps = [s for s in schedule.get("steps") or [] if s.get("enabled", True)]
    run_id = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    write_latest(run_id)
    write_state(
        {
            "run_id": run_id,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "current_step": None,
            "steps_total": len(steps),
            "steps_done": 0,
            "advance_mode": schedule.get("advance_mode", "complete_or_timeout"),
        }
    )
    log(f"Run {run_id}: {len(steps)} steps (mode={schedule.get('advance_mode')})")
    for i, step in enumerate(steps):
        write_state(
            {
                "run_id": run_id,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "current_step": step.get("id"),
                "current_label": step.get("label"),
                "steps_total": len(steps),
                "steps_done": i,
                "advance_mode": schedule.get("advance_mode", "complete_or_timeout"),
            }
        )
        t0 = time.time()
        step_started = datetime.now(timezone.utc).isoformat()
        entry = {
            "run_id": run_id,
            "at": step_started,
            "step_id": step.get("id"),
            "type": step.get("type"),
            "label": step.get("label"),
            "target": step.get("target"),
            "critical": bool(step.get("critical")),
            "timeout_min": step_timeout_min(step),
        }
        try:
            result = run_step(step, args.dry_run, step_started)
            entry["ok"] = bool(result.get("ok", True))
            entry["result"] = result.get("result") or result
            entry["result_text"] = result.get("result_text")
            entry["step_started_at"] = result.get("step_started_at", step_started)
            entry["step_finished_at"] = result.get("step_finished_at")
            entry["duration_s"] = round(time.time() - t0, 1)
            entry["took_s"] = entry["duration_s"]
            entry["timed_out"] = bool(result.get("timed_out"))
            entry["advance_reason"] = result.get("advance_reason", "complete")
            append_run(entry, run_id)
            log(f"OK {step.get('label')} ({entry['duration_s']}s, {entry['advance_reason']})")
        except Exception as exc:
            entry["ok"] = False
            entry["error"] = str(exc)
            entry["result_text"] = str(exc)
            entry["step_started_at"] = step_started
            entry["step_finished_at"] = datetime.now(timezone.utc).isoformat()
            entry["duration_s"] = round(time.time() - t0, 1)
            entry["took_s"] = entry["duration_s"]
            append_run(entry, run_id)
            log(f"FAIL {step.get('label')}: {exc}")
            write_state(
                {
                    "run_id": run_id,
                    "status": "failed",
                    "error": str(exc),
                    "steps_done": i,
                    "steps_total": len(steps),
                }
            )
            if step.get("critical"):
                return 1
    write_state(
        {
            "run_id": run_id,
            "status": "done",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "steps_done": len(steps),
            "steps_total": len(steps),
        }
    )
    log(f"Done run {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
