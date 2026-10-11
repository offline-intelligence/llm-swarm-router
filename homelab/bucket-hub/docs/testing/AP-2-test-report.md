# AP-2 test report

## 1. Scope

Covers audit findings **H2, H3, H4, M9, M10, L6** (overnight report redesign):

- Run-scoped logs in `overnight-runs/<run_id>.jsonl` + `latest.json`
- `/api/overnight/last-night` outcome, jobs window, warnings from run log only
- Hub Last night card (four lines, no pills/emoji)
- `/overnight` planner: last-run table, compact plan, proportional strip, dirty-only save
- Glance: removed legacy `/status/last-night*.html` links

## 2. Automated tests

| File | Test | Proves | Finding |
|------|------|--------|---------|
| `test_overnight_report.py` | `test_run_spanning_midnight_one_file` | One jsonl per run, four steps | H2 |
| | `test_two_runs_same_day_reported_separately` | Latest run + `/api/overnight/runs` | H2 |
| | `test_noncritical_failure_is_attention` | `outcome_for` attention | H3 |
| | `test_critical_failure_is_failed` | Critical fail → failed | H3 |
| | `test_all_ok` | All steps ok | H3 |
| | `test_jobs_window_uses_run_bounds` | `jobs_in_window` | M9 |
| | `test_first_failure_named_and_humanised` | Earliest failure + `humanise_error_text` | M9 |
| | `test_stale_heartbeat_fails_mount_check` | `heartbeat_fresh` | M10 |
| | `test_wake_requires_new_heartbeat` | Wake poll + limit copy | M10 |
| | `test_last_night_api_shape` | API fields + legacy `run`/`steps` | H4 |
| | `test_no_run_recorded` | Empty runs message | H4 |
| | `test_warnings_from_run_log_only` | No live heartbeat warnings | L6 |
| | `test_disabled_steps_excluded_from_strip` | `enabled_step_limits_min` | M9 |
| | `test_warnings_from_run_lines_helper` | Run log warnings | L6 |
| `test_form_escaping.py` | `loadNightSummary` guard (extended allow-list) | Card escaping | H1 |

## 3. Run log

Command (from `homelab/bucket-hub`):

```bash
PYTHONPATH=. uv run --with pytest pytest tests/ -q
```

Date: 2026-10-12.

| When | Result |
|------|--------|
| **Before** (AP-1 complete) | **110 passed** |
| **After** | **124 passed** in 2.36s (`uv run --with pytest`) |

## 4. Manual smoke (Finn)

| Step | Command / action | Result |
|------|------------------|--------|
| 1 | `python3 scripts/overnight-run.py --dry-run` on Pi; check new `overnight-runs/<run_id>.jsonl` and Hub Last night card (four lines) | |
| 2 | Open `/overnight`: Last run table, plan, disabled collapsed, strip + limits line, Save only after edit | |
| 3 | Glance Dev bookmarks: no `/status/last-night*.html` | |
| 4 | Next morning: card matches jsonl + queue counts | |

Deploy (Pi):

```bash
cd homelab/bucket-hub
scripts/verify-deploy-parity.sh pi   # before/after
# rsync manifest pi files to stackrise-pi:~/homelab/hub-form/
# restart hub-form + Glance; bump ?v= in glance.yml iframe URLs
scripts/verify-deploy-parity.sh pi
```

## 5. Not tested and why

- Live `machine_wake` SSH/WoL and TNAS ping on hardware (unit tests use pure helpers).
- `overnight-run.py` full multi-step run on Pi (manual §3.4).
- Browser Playwright for `/overnight` (no e2e harness in bucket-hub).
