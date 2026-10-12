# AP-5a.2 round 2: nightly-step ssh key + schedule check, redeploy + QC (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`).
- Do not edit application code, tests, `Caddyfile`, `glance.yml` or `scripts/smoke-*.sh`.
- No env changes are needed this round. If one turns out to be needed, print the exact non-secret line for Finn to add; Finn adds it. Never print a token, key or cookie (a key's file name is fine).
- If a check fails, record a finding with `repro`, stop the steps that depend on it, and carry on with the independent ones.

Protocol: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (`bucket-hub-qc/v1`), including the PR-comment rule.

PM REVIEW OF `AP-5a2-r1.json`: **fail accepted**; both findings are fixed in the PM code below. C0–C4 and the catalogue numbers (13 403 items, 235 773 files, search ≤ 0.01 s) are accepted and are not re-run except as part of the full smoke.
- **F1 (C5, real bug).** The Pi timer runs `overnight-run.py` with only `HUB_BASE`, `JOBS_DIR` and `HUB_TZ` set, so `MACHINES_SSH_IDENTITY` was empty and ssh used the Pi user's default key, which ai-server refuses. Every nightly ai-server step (index rebuild, ai-server sleep, download drain over ssh) would have failed the same way. Fix: `overnight-run.py` now falls back to `$JOBS_DIR/machines_ssh`, the key the Hub already uses for ai-server (machines + vLLM controls). C5 now runs with `env -u MACHINES_SSH_IDENTITY`, the same as the timer.
- **F2 (C6, smoke error).** The migration did the right thing: Finn's live schedule has no enabled "Sleep ai-server" step, so the rebuild step was added last. C6 now passes when `index_rebuild` is just before `machine_sleep` if that step is enabled, and otherwise last.
- **r1 deviation noted.** Your bulk manifest loop copied only `app.py` and `hub-worker.py`, and the rest went by a targeted rsync. This round, deploy by walking **every** path in the `[pi]` section (and `[worker]` if parity shows a difference), and show that with `verify-deploy-parity.sh` exit 0.

WHAT CHANGED (PM commit on the local branch `pm/ap-5a2-r2`, held in the worktree `.tmp-hub-ui/wt-ap5a2r2`, on top of your `18979f9`; tests 340 → 342):
- `scripts/overnight-run.py`: the `SSH_IDENTITY` fallback above (+5/−1). Deployed on the Pi only.
- `scripts/smoke-ap5a2-catalog.sh`: C5 `env -u`, and C6 as above. Runs on the Mac.
- `tests/test_hub_index.py`: `test_r2_overnight_ssh_key_falls_back_to_the_hub_key`, `test_r2_schedule_without_a_sleep_step_gets_the_rebuild_last`.
- Docs: spec § "AP-5a.2 as built" r2 bullet, test report rows, PROJECT-STATE session row, this prompt as `handoffs/AP-5a2-r2.md`.

OUTPUT: `homelab/bucket-hub/docs/pm/2026-10/qc/AP-5a2-r2.json`, committed on `pm/ap-5a2`, pushed (PR #14). Reply = that JSON in one ```json block, then at most 5 lines.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/2026-10/qc/AP-5a2-r1.json` (your r1 findings)
2. `homelab/bucket-hub/docs/pm/2026-10/AP-5-index-architecture-v2.md` § AP-5a.2 as built (last bullet is r2)
3. `homelab/bucket-hub/docs/testing/AP-5a2-test-report.md`

## S0 git + unit

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
git checkout pm/ap-5a2 && git merge --ff-only pm/ap-5a2-r2 && git log --oneline -3
git worktree remove --force .tmp-hub-ui/wt-ap5a2r2 && git branch -d pm/ap-5a2-r2 && rm -f .tmp-hub-ui/r2patch.py
cd homelab/bucket-hub && PYTHONPATH=. uv run python -m pytest -q 2>&1 | tail -1 && cd ../..
git push offline-intelligence pm/ap-5a2
```

`.tmp-hub-ui/wt-ap5a2` and `.tmp-hub-ui/wt-backlog` are leftover folders from earlier rounds (no longer registered worktrees). Leave them; they are untracked scratch.

| id | expected |
|----|----------|
| `git.ff` | fast-forward to the PM r2 commit; PR #14 head = that commit |
| `unit.pytest` | `342 passed`, 0 failed (`huggingface_hub==0.26.2` as before) |

## S1 key check (read-only)

```bash
ssh stackrise-pi 'J=$(systemctl --user show hub-form -p Environment | tr " " "\n" | sed -n "s/^JOBS_DIR=//p"); J=${J:-$HOME/homelab/data/hub-jobs}; ls -l "$J/machines_ssh" | awk "{print \$1, \$NF}"; ssh -o BatchMode=yes -o ConnectTimeout=10 -i "$J/machines_ssh" bucket@192.168.50.65 "echo ok \$(hostname)"'
```

| id | expected |
|----|----------|
| `info.key` | the key file exists with mode `-rw-------`, and ssh prints `ok <hostname>` |

If ssh with that key fails, record it as finding F1b with the error line and continue with S2; C5 will fail the same way. The PM then decides.

## S2 deploy

```bash
./scripts/verify-deploy-parity.sh pi; ./scripts/verify-deploy-parity.sh worker   # before: pi differs on scripts/overnight-run.py only; worker should already be 0
```

Deploy the `[pi]` manifest set from `pm/ap-5a2`, walking every path in that section. If worker parity is not 0, deploy the `[worker]` set the same way. No service restart is needed on the Pi (`overnight-run.py` is read fresh by each timer run); do not restart `hub-form`. Then:

```bash
./scripts/verify-deploy-parity.sh pi; ./scripts/verify-deploy-parity.sh worker
```

| id | expected |
|----|----------|
| `deploy.pi_parity` / `deploy.worker_parity` | exit 0 each, after |
| `deploy.method` | `manifest loop, all paths` (state the number of paths copied) |

## S3 smoke

Run it alone (no other job queued). The catalogue is already built, so C1 is quick; C4 re-archives the tiny HF smoke model as in r1.

```bash
QC_OUT=/tmp/ap5a2-r2-qc.json ./scripts/smoke-ap5a2-catalog.sh 2>&1 | tee /tmp/ap5a2-r2-smoke.log
```

| id | expected |
|----|----------|
| `smoke.c0_prereqs` … `smoke.c6_schedule` | all `pass`; C5's detail shows the counts line (`N new, N changed, N missing, N deleted`) |

## S4 numbers for the PM (read-only)

```bash
ssh ai-server-ts 'curl -s 127.0.0.1:3031/health | jq "{items, files, db_bytes, last_rebuild}"'
ssh ai-server-ts 'journalctl --user -u hub-index --since "-1 day" --no-pager | grep -cE "WARNING|ERROR"'
curl -s http://100.85.42.0:3000/api/overnight/schedule | jq -c '[.schedule.steps[] | {type, enabled}]'
```

| id | expected |
|----|----------|
| `info.catalogue` | the health JSON |
| `info.warnings` | the count (and up to 5 lines if not 0) |
| `info.schedule` | the step list (the PM is checking which nightly steps are enabled) |

## overall

`pass` only if every non-`info` check is `pass`. Commit the QC file and the docs below on `pm/ap-5a2`, push, and post the QC PR comment on #14. If `pass`: `gh pr ready 14`, then **the PM names this merge**: `gh pr merge 14 --merge`, and record `git.merged` (merge SHA) in `AP-5a2-r2.json`. If not `pass`: do not merge.

## DOCUMENTS TO UPDATE (only these, on `pm/ap-5a2` before the merge)

- `qc/AP-5a2-r2.json` (new).
- `docs/testing/AP-5a2-test-report.md`: one "Manual acceptance" row (r2, date, overall, file).
- `docs/agent-context/PROJECT-STATE.md`: one session-log row citing the file; tick the AP-5a.2 backlog line if `pass`.
- `TODO.md`: tick the AP-5a.2 line if `pass`.
- `CHANGELOG.md`: "Deployed 2026-10-1x, QC r2 <overall>" under AP-5a.2.

## NEXT STEPS (for your information; nothing to do now)

1. PM builds **AP-9.1** video polish. Then Cursor deploys and QCs it, with a smoke on the probe r2 YouTube and X clips.
2. PM writes the **REPO-SYNC** spec (nightly freshness check of archived repos; it uses this catalogue).
3. **AP-5b**: the Hub Index panel, the Pi search proxy, and the fallback that uses the snapshot this packet pushes.
