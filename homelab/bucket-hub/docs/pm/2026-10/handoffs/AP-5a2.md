# AP-5a.2 round 1: ai-server download catalogue, deploy + QC (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`).
- Do not edit application code, tests, `Caddyfile`, `glance.yml` or `scripts/smoke-*.sh`.
- No env changes are needed this round. If one turns out to be needed, print the exact non-secret line for Finn to add; Finn adds it. Never print a token, key or cookie.
- If a check fails, record a finding with `repro`, stop the steps that depend on it, and carry on with the independent ones.

Protocol: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (`bucket-hub-qc/v1`), including the new rule: after writing the QC file, post its summary as a PR comment.

PM REVIEW OF `DOCS-1-r1.json`: **pass accepted**; PR #13 is merged (`c71bb69`). Your closeout commit `bcfe9b3` went straight to `main`. It is docs only, so it is accepted, but from now on QC closeouts go on the packet branch before the merge.

WHAT AP-5a.2 IS (PM commit on the local branch `pm/ap-5a2`, held in the worktree `.tmp-hub-ui/wt-ap5a2`, on top of `bcfe9b3`; tests 316 → 340; the handoff is also in the repo as `docs/pm/2026-10/handoffs/AP-5a2.md`):
- New `hub_index.py` on ai-server, run as the user unit `hub-index.service` on `:3031`. It is a SQLite FTS5 catalogue at `~/homelab/data/hub-index/catalog.sqlite` on the system SSD. It holds:
  - every Pi journal record (tailed every 30 s);
  - every file on every mounted drive, grouped into items.
- Scans are incremental and run in a child process with a time limit. Drives are only read, never written.
- Statuses: an unmounted drive's rows are `offline`; a file gone on a mounted drive is `missing`; a Hub delete is `deleted`. Both `missing` and `deleted` are purged after 30 days.
- `hub-worker.py` nudges `/ingest` when a job finishes.
- New overnight step type `index_rebuild`. `app.py` adds it once to the live schedule, just before "Sleep ai-server". It runs `hub_index.py rebuild` over ssh and pushes an item snapshot to the Pi via the new `PUT /api/index/snapshot` (worker token).
- No Hub UI change yet: the search box and the Pi fallback are AP-5b. The planner only gains the step type.
- Spec `docs/pm/2026-10/AP-5-index-architecture-v2.md` § "AP-5a.2 as built" lists the changes from the plan. Operator doc: `docs/DOWNLOAD-INDEX.md` § "Catalogue on ai-server".

OUTPUT: `homelab/bucket-hub/docs/pm/2026-10/qc/AP-5a2-r1.json`, committed on `pm/ap-5a2`, pushed, with a draft PR to `main`. Reply = that JSON in one ```json block, then at most 5 lines.

## READ FIRST

1. `homelab/bucket-hub/docs/DOWNLOAD-INDEX.md` § Catalogue on ai-server
2. `homelab/bucket-hub/docs/pm/2026-10/AP-5-index-architecture-v2.md` § AP-5a.2 as built
3. `homelab/bucket-hub/docs/testing/AP-5a2-test-report.md`

## S0 git + unit

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
git worktree remove --force .tmp-hub-ui/wt-ap5a2 && rm -f .tmp-hub-ui/ap5a2-base.tgz .tmp-hub-ui/ap5a2-changes.tgz
git fetch offline-intelligence main && git checkout pm/ap-5a2 && git rebase offline-intelligence/main && git log --oneline -3
cd homelab/bucket-hub && PYTHONPATH=. uv run python -m pytest -q 2>&1 | tail -1
git push -u offline-intelligence pm/ap-5a2
gh pr create --draft --base main --head pm/ap-5a2 --title "AP-5a.2: ai-server download catalogue (search every drive) + nightly rebuild"
```

Check `git show --stat pm/ap-5a2` first: one PM commit with 17 files (under `homelab/bucket-hub/`, plus root `CHANGELOG.md`). The worktree has nothing uncommitted; `--force` only covers its untracked `__pycache__`.

| id | expected |
|----|----------|
| `git.rebase` | clean; only the AP-5a.2 commit above `main` |
| `unit.pytest` | `340 passed`, 0 failed (`huggingface_hub==0.26.2` as before) |
| `git.pr` | draft PR URL |

## S1 ai-server prerequisites (read-only)

```bash
ssh ai-server-ts 'python3 --version; python3 -c "import sqlite3; c=sqlite3.connect(\":memory:\"); c.execute(\"create virtual table t using fts5(a)\"); print(\"fts5 ok\", sqlite3.sqlite_version)";
  command -v mountpoint; df -h --output=target,size,avail ~/homelab/data | tail -1; ss -ltn | grep -c ":3031 " || true;
  loginctl show-user "$USER" -p Linger; for m in /mnt/tnas /mnt/media /mnt/external/*; do mountpoint -q "$m" && echo "mounted $m" || echo "not mounted $m"; done'
```

| id | expected |
|----|----------|
| `info.ai_server` | Python ≥ 3.10, `fts5 ok`, `mountpoint` present, `~/homelab/data` on `/`, nothing on 3031, `Linger=yes`, and which roots are mounted |

Stop if FTS5 is missing or 3031 is taken; report it.

## S2 deploy

```bash
./scripts/verify-deploy-parity.sh worker; ./scripts/verify-deploy-parity.sh pi   # before: the new/changed files differ (expected)
```

Deploy the `[worker]` and `[pi]` manifest sets from `pm/ap-5a2` as in earlier rounds. `pm/ap-5a2` = `main` + this packet, so a full-set copy is safe. Do **not** copy from any other branch.

Then:

```bash
ssh ai-server-ts 'systemctl --user enable --now ~/homelab/scripts/scripts/systemd/hub-index.service && systemctl --user restart hub-worker && sleep 5 && systemctl --user is-active hub-index hub-worker'
ssh stackrise-pi 'systemctl --user restart hub-form.service && sleep 3 && systemctl --user is-active hub-form'
ssh ai-server-ts 'journalctl --user -u hub-index --since "-2 min" --no-pager | tail -20'
```

| id | expected |
|----|----------|
| `deploy.worker_parity` / `deploy.pi_parity` | exit 0 each |
| `deploy.services` | `hub-index`, `hub-worker`, `hub-form` all active; no traceback in the hub-index log ("first start: full rebuild" is expected) |

## S3 smoke

Run it alone: no other job should be queued meanwhile. C1 waits up to 30 min for the first full rebuild, and C4 re-archives the tiny HF smoke model as in AP-5a.1 X6.

```bash
QC_OUT=/tmp/ap5a2-qc.json ./scripts/smoke-ap5a2-catalog.sh 2>&1 | tee /tmp/ap5a2-smoke.log
```

| id | expected |
|----|----------|
| `smoke.c0_prereqs` … `smoke.c6_schedule` | all `pass` |

If C5 fails on ssh authentication from the Pi to ai-server, record which key the timer-run `overnight-run.py` uses (`MACHINES_SSH_IDENTITY` set or not, the key's file name only) and continue. The PM then decides how the nightly step reaches ai-server.

## S4 numbers for the PM (read-only)

```bash
ssh ai-server-ts 'curl -s 127.0.0.1:3031/health | jq "{items, files, db_bytes, last_rebuild, roots: [.roots[] | {root_id, mounted, last_full_scan, files}]}"'
ssh ai-server-ts 'for q in office llama heat; do /usr/bin/time -f "$q %es" curl -s -o /dev/null "127.0.0.1:3031/search?q=$q&scope=all"; done'
ssh ai-server-ts 'journalctl --user -u hub-index --no-pager | grep -E "WARNING|ERROR" | tail -10'
```

| id | expected |
|----|----------|
| `info.catalogue` | the health JSON above |
| `info.search_ms` | the three timings |
| `info.warnings` | the log lines, or none |

## overall

`pass` only if every non-`info` check is `pass`. If `pass`: post the QC PR comment, `gh pr ready <n>`, then **the PM names this merge**: `gh pr merge <n> --merge`, and record `git.merged`. If not `pass`: do not merge.

## DOCUMENTS TO UPDATE (only these, on `pm/ap-5a2` before the merge)

- `qc/AP-5a2-r1.json` (new).
- `docs/testing/AP-5a2-test-report.md`: one "Manual acceptance" row (r1, date, overall, file).
- `docs/agent-context/PROJECT-STATE.md`: one session-log row citing the file; tick the AP-5a.2 backlog line if `pass`.
- `TODO.md`: tick the AP-5a.2 line if `pass`.
- `CHANGELOG.md`: "Deployed 2026-10-1x, QC r1 <overall>" under AP-5a.2.

## NEXT STEPS (for your information; nothing to do now)

1. PM builds **AP-9.1** video polish. Then Cursor deploys and QCs it, with a smoke on the probe r2 YouTube and X clips.
2. PM writes the **REPO-SYNC** spec (nightly freshness check of archived repos; it uses this catalogue).
3. **AP-5b**: the Hub Index panel, the Pi search proxy, and the fallback that uses the snapshot this packet pushes.
