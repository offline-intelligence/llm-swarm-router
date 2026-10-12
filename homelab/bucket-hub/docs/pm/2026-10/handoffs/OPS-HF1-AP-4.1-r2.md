# OPS-HF1 gateway deploy + AP-4.1 QC round 2 (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). You do not edit application code, tests, `Caddyfile`, `glance.yml` or `scripts/smoke-*.sh`. On a failing check: record a finding with `repro`, stop dependent steps, continue only with independent checks, return the report. Never print or log a token value.

REPLY TO YOUR LAST REPORT (`AP-4.1-r1.json`, overall `blocked`, F1 `HF_TOKEN` unset) and Finn's status report:
- F1: Finn has set `HF_TOKEN` in `hub-worker.env`. Presence check only; the worker must be restarted to load it (Part C), which r1 did not do. The token stays active while these tests run; Finn revokes and replaces it himself in a few days. Never print it.
- Your P0 (`escHtml is not defined`, Glance queue broken) is fixed in code: the gateway Caddyfile had no `/assets/hub-escape.js` route. PM commit `4458018` on `pm/ap-4.1` adds the route, a `[gateway]` manifest section (Caddyfile + glance.yml → `~/homelab/glance/`), `verify-deploy-parity.sh gateway`, and a test that fails when any page references an `/assets/` file the gateway does not route. 241 tests pass.
- Your P1 is adopted: the Pi restart is `systemctl --user restart hub-form.service` (already in `05-OPERATIONS-SSH-DEPLOY.md`).
- PM found an uncommitted, indentation-damaged `hub-worker.py` in the Mac checkout (16:42 AEST, after your 16:21 worker deploy). PM restored it from HEAD; the damaged diff is in `.tmp-hub-ui/hub-worker-indent-damage-2026-10-12T0642.patch` (do not apply it, do not commit `.tmp-hub-ui/`). Part B proves the deployed copy is clean.
- New specs exist for the next packets (`ROADMAP-2026-10.md`, `AP-UX-1-download-presets.md`, `AP-5-index-architecture-v2.md`). They are for reading only this round; no presets or index work.

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (schema `bucket-hub-qc/v1`).

OUTPUT: write two files, commit both on `pm/ap-4.1`, push:
- `homelab/bucket-hub/docs/pm/2026-10/qc/OPS-HF1-r1.json` (Parts A–B)
- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-4.1-r2.json` (Parts C–E; leave `AP-4.1-r1.json` unchanged)

Reply = both JSONs, each in its own ```json block, first; then at most 5 lines. If you stop at the Finn checkpoint in Part D, reply with the partial `AP-4.1-r2.json` (`overall` = `blocked`, reason `awaiting Finn accept`) and wait.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md`
2. `homelab/bucket-hub/docs/pm/2026-10/ROADMAP-2026-10.md` (why this order; tasks 2–6 are this round)
3. `homelab/bucket-hub/docs/pm/2026-10/handoffs/AP-4.1.md` (B3–B5 are reused below)
4. `homelab/bucket-hub/docs/pm/2026-10/qc/AP-4.1-r1.json`
5. `homelab/bucket-hub/docs/agent-context/05-OPERATIONS-SSH-DEPLOY.md` § "Gateway (hub-gateway Caddy + Glance) on the Pi"

## INPUT

| Key | Value |
|-----|-------|
| packets / rounds | `OPS-HF1` / `1`, then `AP-4.1` / `2` |
| branch / PR | `pm/ap-4.1` / #7 (draft, base `pm/ap-4`; do not retarget this round) |
| expected local HEAD before you start | `4458018` + PM docs commit(s) on top (`git log --oneline -4`); remote is behind by these commits |
| carried from r1 | `git.rebase`, `deploy.pi_parity`, `deploy.pi_app_reloaded`, `deploy.gate_endpoint`, `deploy.form_gate_ui`: copy into `AP-4.1-r2.json` with `"evidence": "carried from AP-4.1-r1.json"` (no Pi app change since r1) |
| Finn supplies | the UI confirmation and "accepted" (Part D). `GATE_REPO` is chosen by the PM (Part D) |
| Finn authorised (2026-10-12) | Cursor carries out MERGE-1 (Part F) |

## Part 0 — git (both reports use these)

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
git status -sb && git log --oneline -5
cd homelab/bucket-hub && python3 -m pytest -q 2>&1 | tail -3
cd ../.. && git push -u origin pm/ap-4.1
```

| id | expected |
|----|----------|
| `git.clean_code` | `git status` shows no modified tracked files under `homelab/bucket-hub/` except docs you are about to write (untracked drafts are fine; do not add them) |
| `unit.pytest` | `241 passed` (or more), 0 failed |
| `git.push` | push ok; `value` = pushed sha |

## Part A — OPS-HF1 gateway deploy (Pi)

The live gateway files may have drifted from the repo. Back up and diff before copying:

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router/homelab/bucket-hub
ssh stackrise-pi 'cd ~/homelab/glance && cp Caddyfile Caddyfile.bak-2026-10-12 && cp glance.yml glance.yml.bak-2026-10-12'
ssh stackrise-pi 'cat ~/homelab/glance/Caddyfile' | diff - Caddyfile; echo "caddy_diff_exit=$?"
ssh stackrise-pi 'cat ~/homelab/glance/glance.yml' | diff - glance.yml; echo "glance_diff_exit=$?"
```

If the Caddyfile diff contains anything other than the new `handle /assets/hub-escape.js { … }` block, or the glance.yml diff is non-empty, **stop Part A**: record finding `gateway drift` with the diff (redact anything that looks like a key or password) and continue with Part B. Live-only lines must not be overwritten without the PM.

Otherwise:

```bash
scp Caddyfile glance.yml stackrise-pi:~/homelab/glance/
ssh stackrise-pi 'docker restart hub-gateway glance && sleep 5 && docker ps --format "{{.Names}} {{.Status}}" | grep -E "hub-gateway|glance"'
./scripts/verify-deploy-parity.sh gateway; echo "exit=$?"
curl -s -o /dev/null -w '%{http_code}\n' http://100.85.42.0:3000/assets/hub-escape.js
curl -s http://100.85.42.0:3000/assets/hub-escape.js | grep -c 'function escHtml'
for p in /assets/hub-overnight.js /assets/hub-design.css /hub-form/; do printf '%s ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' "http://100.85.42.0:3000$p"; done
```

| id | expected |
|----|----------|
| `gateway.drift` | Caddyfile diff = only the new block; glance.yml diff empty. `value` = `{caddy_lines_changed, glance_diff_empty}` |
| `gateway.restart` | both containers `Up` |
| `gateway.parity` | `verify-deploy-parity.sh gateway` exit 0 |
| `gateway.escape_js` | `200`, and `function escHtml` count ≥ 1 |
| `gateway.other_assets` | all three `200` (no regression) |
| `ui.glance_queue` | Finn (or you, in a browser) opens the Glance page at `http://100.85.42.0:3000/`, Queue panel lists jobs, DevTools console has no `escHtml is not defined`. `value` = who checked and what they saw |

Rollback if anything above fails after the copy: `ssh stackrise-pi 'cd ~/homelab/glance && cp Caddyfile.bak-2026-10-12 Caddyfile && cp glance.yml.bak-2026-10-12 glance.yml && docker restart hub-gateway glance'`, record it in `deviations`.

## Part B — worker sanity (ai-server; independent of Part A)

```bash
ssh ai-server-ts 'python3 -m py_compile ~/homelab/scripts/hub-worker.py && echo compile_ok'
./scripts/verify-deploy-parity.sh worker; echo "exit=$?"
```

| id | expected |
|----|----------|
| `worker.compiles` | `compile_ok` |
| `worker.parity` | exit 0 (deployed copy = repo HEAD, so the damaged Mac copy never shipped) |

If either fails: do **not** redeploy; finding with the output, and skip Parts C–E.

`OPS-HF1-r1.json` `overall` = `pass` only if every non-`info` check in Parts 0, A and B is `pass`.

## Part C — AP-4.1 r2 env + worker restart

```bash
ssh ai-server-ts "grep -c '^HF_TOKEN=hf_' ~/homelab/scripts/hub-worker.env"
ssh ai-server-ts 'systemctl --user restart hub-worker && sleep 120 && systemctl --user is-active hub-worker && journalctl --user -u hub-worker --since "-2min" --no-pager | grep -cE "loop error|Traceback|hub http 4" || true'
```

| id | expected |
|----|----------|
| `deploy.env_hf_token` | `1` (closes r1 F1; value never printed) |
| `deploy.worker_service` | `active` |
| `deploy.worker_log` | `0` |
| `deploy.worker_parity` | re-use `worker.parity` from Part B |

## Part D — gated model and phase 1

Finn asked for a gated model of about 20 GB. PM choice, in order (use the first that passes both checks below):

1. `google/gemma-2-9b`
2. `google/gemma-2-9b-it`
3. none left: stop, finding `no GATE_REPO`, ask the PM.

Check 1 is `AP-4.1.md` **B3** (public metadata): `gated` = `"auto"` and `st_bytes` ≤ 20 000 000 000 (the smoke job's cap is `max_size_mb` 20480; the post-download check allows 110 %).

Check 2, not yet accepted by Finn's account (status code only, token over stdin, never in argv or output):

```bash
ssh ai-server-ts 'set -a; . ~/homelab/scripts/hub-worker.env; set +a; printf "Authorization: Bearer %s\n" "$HF_TOKEN" | curl -sS -o /dev/null -I -w "%{http_code}\n" -H @- "https://huggingface.co/'"$GATE_REPO"'/resolve/main/config.json"'
```

`403` (or `401`) = not accepted, usable. `200` = Finn already has access, try the next candidate. Record both checks per candidate in `info.gate_repo` `value`.

A ~18 GB download through Gluetun can take longer than the smoke's default 1 h wait, so phase 2 runs with `WAIT_S=14400` (an env var; the script is unchanged). Check free space first: `ssh ai-server-ts 'df -BG /mnt/tnas | tail -1'` ≥ 40 GB free, else finding.

Then run `AP-4.1.md` **B4** exactly as written, with these file names instead of the r1 ones: `QC_OUT=/tmp/ap41r2-p1.json`, log `/tmp/ap41r2-p1.log`. Start the token sampler (B4) before phase 1 so it covers phase 2. No restarts or env edits from the start of phase 1 to the end of Part E.

Then stop and ask Finn the two B4 questions in chat. Checks `info.gate_repo`, `smoke.gate_precheck`, `smoke.gate_check_404`, `smoke.g_waiting`, `smoke.g_waiting_stable`, `ui.licence_needed` as in `AP-4.1.md`. `ui.licence_needed` depends on Part A: if `gateway.escape_js` failed, mark it `blocked` with reason `Glance queue broken (OPS-HF1)`.

## Part E — phase 2 and disk checks (after Finn says "accepted")

Run `AP-4.1.md` **B5** exactly as written, with `WAIT_S=14400 QC_OUT=/tmp/ap41r2-p2.json`, log `/tmp/ap41r2-p2.log`. The token sampler (1200 × 0.2 s) covers the start of phase 2; that is enough, do not extend it. Checks `smoke.g_check_now`, `smoke.g_done`, `smoke.g_index`, `live.hf_layout`, `live.hf_real_weights`, `live.no_partials`, `live.index_rows`, `live.token_not_in_ps`. Also record:

| id | expected |
|----|----------|
| `info.gate_wait_s` | `gate_wait_s` from the index row (any number) |

Afterwards dismiss the smoke jobs (`JOBS` line). Leave the archived model on TNAS.

`AP-4.1-r2.json` `overall` = `pass` only if every non-`info` check is `pass`. One smoke run per phase; a re-run is allowed only for a clearly external cause (huggingface.co unreachable), with both runs in `evidence`.

## Part F — MERGE-1 (Finn authorised Cursor to do this, 2026-10-12)

Can run while you wait for Finn in Part D. Uses `gh`; merge commits only (`--merge`), never squash or rebase, because #6 and #7 are stacked on the branches below them. Do not delete branches until #7 is merged.

```bash
gh pr view 5 --json number,state,baseRefName,headRefName,mergeable,statusCheckRollup,isDraft
gh pr view 6 --json number,state,baseRefName,headRefName,mergeable,isDraft
gh pr view 7 --json number,state,baseRefName,headRefName,mergeable,isDraft
```

1. **#5** (`pm/ap-3.1`, QC r4 pass): if `mergeable` = `MERGEABLE` and no failing checks, `gh pr merge 5 --merge`. Record its base as `BASE`.
2. **#6** (`pm/ap-4`, QC r1b pass): `gh pr edit 6 --base "$BASE"`, `gh pr ready 6`, re-check `mergeable`, then `gh pr merge 6 --merge`.
3. **#7** (`pm/ap-4.1`): `gh pr edit 7 --base "$BASE"` only. Merge it **only if** `OPS-HF1-r1.json` and `AP-4.1-r2.json` are both `overall` = `pass`; then `gh pr ready 7 && gh pr merge 7 --merge`. Otherwise leave it draft.
4. Any conflict or failing check: stop that step, finding with the `gh` output, do not resolve conflicts yourself (the PM does).

Record in `AP-4.1-r2.json`:

| id | expected |
|----|----------|
| `merge.pr5` | `MERGED`; `value` = `{base, merge_sha}` |
| `merge.pr6` | retargeted to `BASE` and `MERGED` |
| `merge.pr7` | retargeted to `BASE`; `MERGED` if both reports pass, else `skip` with reason |

`merge.*` checks do not count towards `AP-4.1-r2.json` `overall`.

## DOCUMENTS TO UPDATE (only these)

- `homelab/bucket-hub/docs/pm/2026-10/qc/OPS-HF1-r1.json` (new).
- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-4.1-r2.json` (new).
- `homelab/bucket-hub/docs/testing/AP-4.1-test-report.md`: fill "Manual acceptance" from r2.
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`: one session-log row per report, citing the file; tick OPS-HF1 if its `overall` = `pass`, tick AP-4.1 if its `overall` = `pass`. Keep the existing r1 row.
- `homelab/bucket-hub/TODO.md` ("Active — Repo archive"): tick the matching OPS-HF1 / AP-4.1 lines on `pass`.
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md` backlog: tick the MERGE-1 line when #5 and #6 are merged; note the `BASE` branch.
- `CHANGELOG.md`: one line under the OPS-HF1 entry ("Deployed 2026-10-12, QC r1 <overall>") and one under the AP-4.1 entry ("QC r2 <overall>").
