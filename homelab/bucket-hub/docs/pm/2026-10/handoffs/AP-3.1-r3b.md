# AP-3.1 handoff, round 3b: torrent-bytes re-run only (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC (`homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md`, schema `bucket-hub-qc/v1`). Do not edit application code, tests or `scripts/smoke-*.sh`. No deploy, no restarts, no env edits this round.

OUTPUT: write `homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r3b.json` (`"round": "3b"`), commit on `pm/ap-3.1`, push. Reply = that JSON in one ```json block first, then at most 5 lines.

## PM DIAGNOSIS OF ROUND 3 (input, do not re-litigate)

| finding | PM verdict | action |
|---------|-----------|--------|
| all repo checks (Spoon-Knife 1 MB, 0 `refs/pull`, `HEAD` set, drain, README, token, TNAS re-check) | **pass**; r2 F1 and F2 closed | none |
| r3 F1 `smoke.torrent_bytes_rise` = 0 (Tears of Steel) | **Not an AP-3.1 regression.** The lane fix is the claim, and the torrent was claimed at 10 s with three repo jobs queued ahead. Bytes then depend on the swarm. r1 proved bytes rise during a git/git clone with Sintel (~129 MB). The swap to Tears of Steel was the only change. | re-run the smoke once with the **Sintel** magnet from round 1 |

## INPUT

| Key | Value |
|-----|-------|
| packet / round | `AP-3.1` / `3b` |
| branch / head | `pm/ap-3.1` tip: one PM docs commit on top of `4668a6c`; no new PM code |
| PR | https://github.com/offline-intelligence/llm-swarm-router/pull/5 |
| torrent | the Sintel magnet used in round 1 (same `DRIVE_ID` / `FOLDER_ID`) |

## S0 evidence and prep

```bash
curl -s http://100.85.42.0:3000/api/jobs/648ae5ce9631 | jq -c '{status, error_display, progress}'
curl -s http://100.85.42.0:3000/api/repo-lane | jq -c .
ssh ai-server-ts 'ls -d /mnt/external/movies/torrents/Sintel* 2>/dev/null; true'
```

| id | expected |
|----|----------|
| `info.r3_tears_state` | always `pass`; `value` = the job JSON line (shows whether it was stuck on metadata or peers). Then dismiss `648ae5ce9631` |
| `prep.lane_idle` | `active_repo` = 0 |
| `prep.torrent_dest_clean` | no `Sintel*` folder; if one exists from an AP-3.1 smoke, `mv` it aside (no `rm`) and record in `deviations` |

## S1 smoke, once

Worker must have been up for 2 min with no restarts since round 3.

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router/homelab/bucket-hub
TORRENT_URL='<Sintel magnet from r1>' DRIVE_ID='<id>' FOLDER_ID='<id>' QC_OUT=/tmp/ap31r3b-smoke-qc.json \
  ./scripts/smoke-ap31-lanes.sh 2>&1 | tee /tmp/ap31r3b-smoke.log
```

| id | expected |
|----|----------|
| `smoke.precheck` … `smoke.readme_excerpt` | copied unchanged from `QC_OUT`, all `pass` |

If `smoke.torrent_bytes_rise` fails again with Sintel, add `ssh ai-server-ts 'journalctl --user -u hub-worker --since "-20 min" | grep -iE "aria2|<torrent job id>" | tail -40'` as the finding's evidence and stop. Do not try a third torrent.

## On overall = pass

- Mark PR #5 **ready for review** (out of draft). Do not merge; Finn merges.
- Dismiss the smoke torrent and the four smoke jobs this round created, if your tools allow.

## DOCUMENTS TO UPDATE (only these)

- `homelab/bucket-hub/docs/testing/AP-3.1-test-report.md`: "Round 3b" table.
- `homelab/bucket-hub/docs/testing/AP-3-test-report.md`: §T6 step 2 and 3 status.
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`: if `overall` = `pass`, tick AP-3.1 and its §T6 step 2 sub-item, tick "Re-run §T6 step 2", mark AP-3 done; one session-log row citing `AP-3.1-r3b.json`. Otherwise the row only.
- `CHANGELOG.md`: one line under AP-3.1, "QC r3b <overall>".
- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r3b.json` (new).
