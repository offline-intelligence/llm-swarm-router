# AP-4.2 test report — HF access re-check schedule

**Branch:** `pm/ap-4.2` (on top of `pm/ap-ux-1`). **Spec:** `docs/pm/2026-10/AP-4.2-gate-schedule.md`. **Written by:** PM (2026-10-12).

## What changed

| File | Change |
|------|--------|
| `repo_archive_hf.py` (worker + Pi copy) | `gate_schedule()` / `gate_recheck_seconds(checks)`: gaps 60, 300, 1800, then 3600 s (`HF_GATE_SCHEDULE_S`; legacy `HF_GATE_RECHECK_S` = fixed gap). On access after a wait the job gets `gate.state = granted`, `granted_at`, `next_check: null`, and the licence note is cleared |
| `form.html` | `gateWaiting()` (only `awaiting_licence` / `needs_token` + queued); manual gates say **Approval needed** / **Request access**; "Next automatic check in N min" on cards and bar rows; bar title "Waiting for Hugging Face access (N)" |
| `glance.yml` | iframe `?v=20261012g42` |

## Unit tests (PM)

`PYTHONPATH=. pytest tests/ -q` → **286 passed** (279 + 7 new in `tests/test_repo_archive_hf_gate.py`; G2 expectation 600 s → 60 s).

## Behaviour changes to know about

- Jobs already waiting when this deploys keep their `checks` count, so a job with 18 checks goes straight to the hourly gap. Click Check now on those once.
- If `hub-worker.env` sets `HF_GATE_RECHECK_S`, the old fixed gap wins. Remove that line (Finn) to get the schedule.

## Manual acceptance (Cursor + Finn)

_To be filled by Cursor from `docs/pm/2026-10/qc/AP-4.2-r1.json`._
