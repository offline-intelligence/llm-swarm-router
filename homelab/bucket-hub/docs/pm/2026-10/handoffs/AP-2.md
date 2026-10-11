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

**hub-design.css:** no changes needed (only touched in audit handoff commit `0b89c7e`; AP-2 uses existing tokens via `/assets/hub-design.css`, already in `deploy-manifest.txt`).

**Rebase onto `hub/audit-handoff-2026-10` pending AP-1 merge — not done yet.**

**Post-handoff (2026-10-12 deploy):** Pi + worker rsync done; worker `verify-deploy-parity.sh` exit 0; Pi 22/22 (Tailscale `100.85.42.0`). Commit `9310d1b`: Pi-safe overnight log text + `ssh -n` in parity script. Glance restart not confirmed.

**Tests added (follow-up):** N/A — deploy-only; suite still 124 passed.

Deploy (Finn — mostly done):

```bash
cd homelab/bucket-hub
HUB_PI_SSH=bucket@100.85.42.0  # until ~/.ssh/config HostName fixed
./scripts/verify-deploy-parity.sh worker   # expect exit 0
# Pi parity: use Tailscale IP + id_ed25519_pi; script uses ssh -n as of 9310d1b
ssh -i ~/.ssh/id_ed25519_pi bucket@100.85.42.0 'systemctl --user restart hub-form.service'
# Reload Glance after glance.yml deploy
JOBS_DIR=~/homelab/data/hub-jobs HUB_BASE=http://127.0.0.1:3020 python3 ~/homelab/hub-form/scripts/overnight-run.py --dry-run
```
