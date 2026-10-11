from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from overnight_report import (
    build_last_night,
    enabled_step_limits_min,
    evaluate_machine_wake,
    heartbeat_fresh,
    jobs_in_window,
    list_run_summaries,
    load_latest_run_id,
    machine_wake_poll,
    outcome_for,
    read_run_lines,
    run_file_for,
    warnings_from_run_lines,
)

TZ = ZoneInfo("Australia/Brisbane")


def _iso(y, m, d, h, mi, sec=0):
    return datetime(y, m, d, h, mi, sec, tzinfo=TZ).astimezone(timezone.utc).isoformat()


def test_run_spanning_midnight_one_file(tmp_path):
    run_id = "20261011-220000"
    path = run_file_for(tmp_path, run_id)
    times = [
        _iso(2026, 10, 11, 22, 0),
        _iso(2026, 10, 11, 23, 55),
        _iso(2026, 10, 12, 0, 20),
        _iso(2026, 10, 12, 1, 10),
    ]
    for i, t in enumerate(times):
        row = {
            "label": f"Step {i}",
            "ok": True,
            "critical": True,
            "step_started_at": t,
            "step_finished_at": t,
            "at": t,
        }
        path.write_text(
            (path.read_text(encoding="utf-8") if path.is_file() else "")
            + json.dumps(row)
            + "\n",
            encoding="utf-8",
        )
    lines = read_run_lines(path)
    payload = build_last_night(
        lines,
        [],
        {"window": {"start": "22:00", "end": "06:00"}, "steps": []},
        datetime.now(TZ),
        run_id=run_id,
        tz=TZ,
    )
    assert len(payload["steps"]) == 4


def test_two_runs_same_day_reported_separately(tmp_path, hub_client):
    client, jobs_dir, _app = hub_client
    runs = jobs_dir / "overnight-runs"
    runs.mkdir()
    for rid in ("20261011-140000", "20261011-220000"):
        p = run_file_for(runs, rid)
        p.write_text(
            json.dumps({"label": "Wake ai-server", "ok": True, "critical": True}) + "\n",
            encoding="utf-8",
        )
    (runs / "latest.json").write_text(
        json.dumps({"run_id": "20261011-220000"}) + "\n", encoding="utf-8"
    )
    assert load_latest_run_id(runs) == "20261011-220000"
    listed = list_run_summaries(runs, 7)
    assert len(listed) == 2
    r = client.get("/api/overnight/last-night")
    assert r.status_code == 200
    assert r.json()["run_id"] == "20261011-220000"
    runs_api = client.get("/api/overnight/runs?limit=7")
    assert len(runs_api.json()["runs"]) == 2


def test_noncritical_failure_is_attention():
    steps = [
        {"ok": True, "critical": True},
        {"label": "Wake TNAS", "ok": False, "critical": False},
    ]
    assert outcome_for(steps) == "attention"


def test_critical_failure_is_failed():
    steps = [{"label": "Check drives", "ok": False, "critical": True}]
    assert outcome_for(steps) == "failed"


def test_all_ok():
    steps = [{"ok": True, "critical": True}, {"ok": True, "critical": False}]
    assert outcome_for(steps) == "ok"


def test_jobs_window_uses_run_bounds():
    start = datetime(2026, 10, 11, 22, 0, tzinfo=TZ).astimezone(timezone.utc)
    end = datetime(2026, 10, 12, 1, 10, tzinfo=TZ).astimezone(timezone.utc)
    jobs = [
        {"finished_at": _iso(2026, 10, 11, 21, 59), "status": "done"},
        {"finished_at": _iso(2026, 10, 11, 22, 30), "status": "done"},
        {"finished_at": _iso(2026, 10, 12, 1, 0), "status": "done"},
        {"finished_at": _iso(2026, 10, 12, 7, 0), "status": "done"},
    ]
    in_win = jobs_in_window(jobs, start, end)
    assert len(in_win) == 2


def test_first_failure_named_and_humanised():
    start = datetime(2026, 10, 11, 22, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
    jobs = [
        {
            "finished_at": "2026-10-11T23:00:00+00:00",
            "status": "error",
            "title": "Late show",
            "error": "dead torrent no peers",
        },
        {
            "finished_at": "2026-10-11T22:30:00+00:00",
            "status": "error",
            "title": "Early show",
            "error": "timeout",
        },
    ]
    payload = build_last_night(
        [{"ok": True, "critical": True, "step_started_at": start.isoformat(), "step_finished_at": end.isoformat()}],
        jobs,
        {"window": {"start": "22:00", "end": "06:00"}, "steps": []},
        datetime.now(timezone.utc),
        run_id="x",
    )
    ff = payload["jobs"]["first_failure"]
    assert ff["title"] == "Early show"
    assert ff["error"] == "timeout"


def test_stale_heartbeat_fails_mount_check():
    step_start = _iso(2026, 10, 11, 22, 2)
    hb = _iso(2026, 10, 11, 21, 50)
    assert heartbeat_fresh(hb, step_start) is False
    ok, text = evaluate_machine_wake(
        {"target": "ubuntu", "timeout_min": 5},
        step_start,
        hb,
    )
    assert ok is False
    assert "Stopped after 5 m limit" in text


def test_wake_requires_new_heartbeat():
    step_start = _iso(2026, 10, 11, 22, 0)
    stale = _iso(2026, 10, 11, 21, 55)

    def fetch():
        return stale

    ok, _hb = machine_wake_poll(time.time() + 0.05, 0.01, fetch, step_start)
    assert ok is False
    ok2, text = evaluate_machine_wake(
        {"target": "ubuntu", "timeout_min": 3},
        step_start,
        stale,
    )
    assert ok2 is False
    assert text == "Stopped after 3 m limit"


def test_last_night_api_shape(hub_client):
    client, jobs_dir, _app = hub_client
    runs = jobs_dir / "overnight-runs"
    runs.mkdir()
    rid = "20261011-220000"
    row = {
        "label": "Wake ai-server",
        "ok": True,
        "critical": True,
        "step_started_at": _iso(2026, 10, 11, 22, 0),
        "step_finished_at": _iso(2026, 10, 11, 22, 5),
        "result_text": "OK",
        "took_s": 12,
    }
    run_file_for(runs, rid).write_text(json.dumps(row) + "\n", encoding="utf-8")
    (runs / "latest.json").write_text(json.dumps({"run_id": rid}) + "\n", encoding="utf-8")
    r = client.get("/api/overnight/last-night")
    assert r.status_code == 200
    data = r.json()
    for key in (
        "run_id",
        "started_at",
        "finished_at",
        "outcome",
        "steps",
        "jobs",
        "next_run_at",
        "worker_state",
    ):
        assert key in data
    assert "finished" in data["jobs"]
    assert "failed" in data["jobs"]
    assert "first_failure" in data["jobs"]
    assert "run" in data
    assert isinstance(data["steps"], list)


def test_no_run_recorded(hub_client):
    client, jobs_dir, _app = hub_client
    (jobs_dir / "overnight-runs").mkdir(exist_ok=True)
    r = client.get("/api/overnight/last-night")
    data = r.json()
    assert data.get("run_id") is None
    assert "No run recorded last night" in (data.get("message") or "")


def test_warnings_from_run_log_only(hub_client, monkeypatch):
    client, jobs_dir, app_mod = hub_client
    runs = jobs_dir / "overnight-runs"
    runs.mkdir()
    rid = "20261011-220000"
    run_file_for(runs, rid).write_text(
        json.dumps({"label": "Check drives", "ok": True, "warnings": []}) + "\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(json.dumps({"run_id": rid}) + "\n", encoding="utf-8")

    def fake_worker_state():
        return "ai-server awake"

    monkeypatch.setattr(app_mod, "_worker_state_label", fake_worker_state)
    # If API merged live heartbeat warnings, this would be non-empty; run log has none.
    r = client.get("/api/overnight/last-night")
    assert r.json().get("warnings") == []


def test_disabled_steps_excluded_from_strip():
    schedule = {
        "window": {"start": "22:00", "end": "06:00"},
        "steps": [
            {"enabled": True, "timeout_min": 10},
            {"enabled": True, "timeout_min": 20},
            {"enabled": False, "timeout_min": 5},
            {"enabled": False, "timeout_min": 5},
            {"enabled": False, "timeout_min": 5},
        ],
    }
    total, span, disabled_n = enabled_step_limits_min(schedule)
    assert total == 30
    assert span == 8 * 60
    assert disabled_n == 3


def test_warnings_from_run_lines_helper():
    lines = [{"warnings": ["Disk slow"]}, {"result": {"warnings": ["Disk slow", "VPN"]}}]
    assert warnings_from_run_lines(lines) == ["Disk slow", "VPN"]
