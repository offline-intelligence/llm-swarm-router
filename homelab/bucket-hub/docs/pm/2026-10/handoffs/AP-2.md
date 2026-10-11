## Handoff to PM
**Packet:** AP-2
**Files changed:**
- `overnight_report.py` — pure helpers: run files, outcome, jobs window, heartbeat, `build_last_night`, schedule strip totals
- `scripts/overnight-run.py` — per-run jsonl, latest pointer, wake/mount/queue_drain step semantics
- `app.py` — `/api/overnight/last-night`, `/api/overnight/runs`, worker_state label
- `form.html` — four-line Last night card; Recent jobs moved outside fold; `loadNightSummary` uses `card_lines`
- `overnight.html`, `hub-overnight.js` — Gantt removed; last-run table, compact plan, proportional strip, dirty-only save, Run now hint
- `overnight-schedule.default.json` — British labels (Check drives, Download queue)
- `glance.yml` — removed `/status/last-night*.html` bookmarks and drain archive iframe
- `scripts/deploy-manifest.txt` — `overnight_report.py`, `scripts/overnight-run.py`
- `docs/agent-context/PROJECT-STATE.md` — AP-1 accepted, AP-2 in progress, session log
- `docs/testing/AP-2-test-report.md` — evidence table + 124 passed run log
- `tests/test_overnight_report.py` — §3.3 cases
- `tests/test_form_escaping.py` — allow-list for Last night card tones

**Tests added:** `test_overnight_report.py` (14 tests) — pass; `test_form_escaping.py` — pass; suite **124 passed** (was 110).

**Decisions made:**
- `jobs_in_window` uses `[start, end)` on `finished_at` (UTC-normalised).
- `test_first_failure_named_and_humanised` asserts earliest failure by `finished_at` (error text not reordered across jobs).
- PR branch `cursor/ap-2` stacks AP-1 commits from `cursor/ap-1` (required for 110-test baseline).

**Open questions:** None.

Deploy (Finn):

```bash
cd homelab/bucket-hub
scripts/verify-deploy-parity.sh pi
# rsync Pi manifest (incl. overnight_report.py, scripts/overnight-run.py) to stackrise-pi:~/homelab/hub-form/
# restart hub-form + Glance; bump ?v= on hub iframe URLs in glance.yml
scripts/verify-deploy-parity.sh pi
python3 ~/homelab/hub-form/scripts/overnight-run.py --dry-run
```
