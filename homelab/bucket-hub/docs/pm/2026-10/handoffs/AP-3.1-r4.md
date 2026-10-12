# AP-3.1 handoff, round 4: aria2 errors no longer starve the repo lane (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC (`homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md`, schema `bucket-hub-qc/v1`). Do not edit application code, tests or `scripts/smoke-*.sh`. On a failing check: record a finding with `repro`, stop dependent steps, return the report.

OUTPUT: write `homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r4.json`, commit on `pm/ap-3.1`, push. Reply = that JSON in one ```json block first, then at most 5 lines.

## PM DIAGNOSIS OF ROUND 3b (input, do not re-litigate)

| finding | PM verdict | fix in round 4 |
|---------|-----------|----------------|
| `smoke.torrent_bytes_rise` | **pass** with Sintel (129 MB while git/git cloned). Lane fix proven. | none |
| F1 `smoke.repos_drain` (R2/R3 stuck `queued`, repeated `hub http 400 … Active Download not found for GID#85365f42082a8ffe`) | **Real bug, and the same root cause as r1 F3.** That `400` is not the Hub: aria2 answers a JSON-RPC error with HTTP 400, so `aria2()` raised `urllib.error.HTTPError` instead of `RuntimeError`. `find_resumable_aria2_job()` only catches `RuntimeError`, so on every tick the error escaped to the main loop's `except HTTPError` ("hub http 400"), and the video and repo claims further down the loop never ran. A Hub job still `running` with a gid aria2 had already dropped was enough to stall the repo lane indefinitely. | `hub-worker.py`: `aria2()` turns an HTTP 400 JSON-RPC error into `RuntimeError(<aria2 message>)`; aria2 housekeeping in `main()` (`_recover_claimed_aria2_jobs`, `_aria2_supervisor_tick`, resume/attach) runs in its own `try` and logs `aria2 housekeeping error: …` instead of aborting the tick. 4 new tests, including one that runs `main()` with failing aria2 housekeeping and asserts the `repo` and `repo_meta` lanes are still claimed. |
| F2 `smoke.readme_excerpt` | Downstream of F1. | none |

## INPUT

| Key | Value |
|-----|-------|
| packet / round | `AP-3.1` / `4` |
| branch | `pm/ap-3.1`; PM commits on top of `6babfca` (same Mac checkout) |
| PR | https://github.com/offline-intelligence/llm-swarm-router/pull/5 (stays draft) |
| changed files | `hub-worker.py`, `tests/test_repo_lane_ap31.py`, docs |
| deploy | worker only (`hub-worker.py`); image stays `bucket-hub-repo-archiver:3`; no env change |
| torrent | Sintel magnet (same as r1 and r3b) |

## S0 prep (before the worker restart, so recovery does not pick up old jobs)

```bash
curl -s 'http://100.85.42.0:3000/api/jobs?status=queued&limit=50' | jq -c '[.jobs[] | {id, kind, title}]'
curl -s 'http://100.85.42.0:3000/api/jobs?status=running&limit=50' | jq -c '[.jobs[] | {id, kind, title, aria2_gid}]'
```

| id | expected |
|----|----------|
| `info.r3b_leftovers` | always `pass`; `value` = both lists. Then dismiss the r3b smoke jobs (`7db9557b1999`, `5d70c5dc4710`, and the r3b Sintel torrent `8d817da9a03b`) |
| `prep.torrent_dest_clean` | `ssh ai-server-ts 'ls -d /mnt/external/movies/torrents/Sintel* 2>/dev/null; true'`; if the r3b download is there, `mv` it aside (no `rm`) and record in `deviations`; `value` = paths found |

## S1 integrate

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router && git switch pm/ap-3.1 && git log --oneline -3
git fetch offline-intelligence && git rebase offline-intelligence/main
cd homelab/bucket-hub && PYTHONPATH=. uv run --with pytest pytest tests/ -q 2>&1 | tee /tmp/ap31r4-unit.pytest.log | tail -3
cd ../.. && git push --force-with-lease offline-intelligence pm/ap-3.1
```

| id | expected |
|----|----------|
| `git.rebase` | exit 0, no `*.py`/`*.sh` conflicts |
| `unit.pytest` | `193 passed`, 0 failed |
| `git.push` | PR #5 head = local `HEAD`; `value` = sha |

## S2 deploy worker

rsync the `[worker]` manifest set to `~/homelab/scripts/`, then `ssh ai-server-ts 'systemctl --user restart hub-worker'`.

| id | expected |
|----|----------|
| `deploy.pi_parity` | `verify-deploy-parity.sh pi` exit 0 (no Pi change expected) |
| `deploy.worker_parity` | `verify-deploy-parity.sh worker` exit 0 |
| `deploy.worker_service` | `is-active hub-worker` = `active` |
| `deploy.worker_log` | 120 s after restart: `journalctl --user -u hub-worker --since "-2 min"` has 0 lines matching `loop error\|Traceback\|hub http 4`. No exclusions this round: aria2 RPC errors must no longer appear as `hub http 400`. `value` = count |

## S3 full smoke, once (no restarts, env edits or manual job changes from here on)

Worker up for 2 min, `active_repo` = 0. Sampler first, then the smoke:

```bash
# terminal A
ssh ai-server-ts 'for i in $(seq 1 1200); do ps -eo args | grep -v grep | grep -c "Authorization: Bearer"; sleep 0.2; done | sort -u' \
  | tee /tmp/ap31r4-live.token_not_in_ps.log

# terminal B
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router/homelab/bucket-hub
TORRENT_URL='<Sintel magnet>' DRIVE_ID='<id>' FOLDER_ID='<id>' QC_OUT=/tmp/ap31r4-smoke-qc.json \
  ./scripts/smoke-ap31-lanes.sh 2>&1 | tee /tmp/ap31r4-smoke.log
```

After the smoke:

```bash
ssh ai-server-ts 'journalctl --user -u hub-worker --since "-30 min" | grep -cE "hub http 4|loop error|Traceback"'
ssh ai-server-ts 'journalctl --user -u hub-worker --since "-30 min" | grep -E "aria2 housekeeping error|Active Download not found" | tail -20'
```

| id | expected |
|----|----------|
| `smoke.precheck` … `smoke.readme_excerpt` | copied unchanged from `QC_OUT`, all `pass` |
| `live.token_not_in_ps` | distinct counts = `0` only; 1200 samples |
| `live.loop_clean` | first grep count = `0`; `value` = count |
| `info.aria2_housekeeping` | always `pass`; `value` = second grep lines (or `[]`). Non-empty is fine as long as the smoke passed: it shows the error was contained |

If `smoke.repos_drain` fails, stop and return the report with `curl -s …/api/jobs/<R2 id>` and `<R3 id>` (status, `not_before`, note) and the last 60 worker log lines.

## On overall = pass

- Mark PR #5 **ready for review** (out of draft). Do not merge; Finn merges.
- Dismiss the smoke torrent and smoke repo jobs if your tools allow.

## DOCUMENTS TO UPDATE (only these)

- `homelab/bucket-hub/docs/testing/AP-3.1-test-report.md`: "Round 4" table.
- `homelab/bucket-hub/docs/testing/AP-3-test-report.md`: §T6 step 2 and 3 status.
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`: if `overall` = `pass`, tick AP-3.1, its §T6 step 2 sub-item and "Re-run §T6 step 2", mark AP-3 done; one session-log row citing `AP-3.1-r4.json`. Otherwise the row only.
- `CHANGELOG.md`: one line under AP-3.1, "QC r4 <overall>".
- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r4.json` (new).
