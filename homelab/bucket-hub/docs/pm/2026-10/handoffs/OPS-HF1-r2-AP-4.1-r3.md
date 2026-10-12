# OPS-HF1 round 2 + AP-4.1 round 3 (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). Same rules as `docs/pm/2026-10/handoffs/OPS-HF1-AP-4.1-r2.md`: no edits to application code, tests, `Caddyfile`, `glance.yml` or `scripts/smoke-*.sh`; failing check → finding with `repro`, stop dependent steps; never print a token.

PM REVIEW OF YOUR LAST REPORTS:
- `OPS-HF1-r1.json` F1 (glance.yml drift): the only live-only difference is the iframe cache-buster (`v=20261012ops1` live vs `v=20261012ap41` repo). That line is a cache-buster, not config. PM has bumped the repo to `v=20261012hf1` (commit below), so the deploy also forces browsers to reload the Hub iframe. **Overwriting a difference that is only on `?v=` query values is authorised**; any other difference still stops Part A. F2 (404) closes once Part A runs.
- `AP-4.1-r2.json` F1 (no `GATE_REPO`): PM error. Both Gemma repos report `gated: "manual"`. The Hub's gate flow handles manual gating too (it re-checks every 10 min for up to 168 h), so the "auto only" rule is dropped. **`GATE_REPO = google/gemma-2-9b-it`** (your data: manual, 18 483 466 448 B ≤ 20 GB cap, HEAD 403 = not yet accepted). Google normally grants Gemma access straight after the licence is acknowledged (PM inference, not verified); if it does not, the Hub keeps waiting and Part E records `blocked: awaiting HF approval`.
- MERGE-1: #5 and #6 merged into `main`, #7 retargeted to `main`. Good. #7 merges only when both reports below pass.

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (`bucket-hub-qc/v1`).

OUTPUT: `homelab/bucket-hub/docs/pm/2026-10/qc/OPS-HF1-r2.json` and `homelab/bucket-hub/docs/pm/2026-10/qc/AP-4.1-r3.json` (new files; leave r1/r2 unchanged). Commit on `pm/ap-4.1`, push. Reply = both JSONs in their own ```json blocks, then at most 5 lines. At the Finn checkpoint in Part D, reply with the partial `AP-4.1-r3.json` (`overall` = `blocked`, reason `awaiting Finn accept`) and wait.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/2026-10/handoffs/OPS-HF1-AP-4.1-r2.md` (Parts A, D, E, F are reused)
2. `homelab/bucket-hub/docs/pm/2026-10/qc/OPS-HF1-r1.json`, `AP-4.1-r2.json`
3. `homelab/bucket-hub/docs/pm/2026-10/handoffs/AP-4.1.md` (B4, B5)

## INPUT

| Key | Value |
|-----|-------|
| branch / PR | `pm/ap-4.1` / #7 (draft, base `main`) |
| PM commit | glance.yml cache-buster `v=20261012hf1` + this prompt + state docs (on top of `79cceaa`; `git log --oneline -3`) |
| carried into OPS-HF1-r2 | `worker.compiles`, `worker.parity`, `gateway.other_assets` from r1 (`"evidence": "carried from OPS-HF1-r1.json"`) |
| carried into AP-4.1-r3 | every r2 `deploy.*` check and `merge.pr5`, `merge.pr6` (`"evidence": "carried from AP-4.1-r2.json"`). No worker restart this round |
| `GATE_REPO` | `google/gemma-2-9b-it` |

## Part 0 — git

`git pull --ff-only`, `python3 -m pytest -q` (expect 241 passed), push. Checks `unit.pytest`, `git.push` in `OPS-HF1-r2.json`.

## Part A — gateway deploy (re-run)

Run Part A of `OPS-HF1-AP-4.1-r2.md` with one change to the drift rule:

| id | expected |
|----|----------|
| `gateway.drift` | Caddyfile diff = only the new `hub-escape.js` block; glance.yml diff = only `?v=` values (expected: the one `panel=hub&v=` line). `value` = both diffs, short |

Then the copy, restart, `gateway.restart`, `gateway.parity`, `gateway.escape_js`, `ui.glance_queue` exactly as in r2. Backups from r1 (`*.bak-2026-10-12`) already exist; keep them, do not overwrite. Rollback rule unchanged.

`OPS-HF1-r2.json` `overall` = `pass` only if every non-`info` check is `pass`.

## Part D — phase 1 (only if `gateway.escape_js` = pass)

`GATE_REPO=google/gemma-2-9b-it`. Re-run check 2 from r2 Part D (HEAD with token over stdin) immediately before phase 1: must still be `403`/`401`; if `200`, stop with finding `already accepted` and ask the PM.

Then `AP-4.1.md` **B4** with `QC_OUT=/tmp/ap41r3-p1.json`, log `/tmp/ap41r3-p1.log`, sampler started first. Record `info.gate_repo` = `{repo, gated: "manual", st_bytes, head_before: 403}`, and `smoke.gate_precheck`, `smoke.gate_check_404`, `smoke.g_waiting`, `smoke.g_waiting_stable`.

Stop and ask Finn in chat to:
1. Open the Hub queue (Glance `http://100.85.42.0:3000/`, hard refresh) and confirm the job shows **Licence needed**, an **Accept licence** button and the "Waiting for a licence (1)" bar.
2. Click Accept licence, acknowledge the Gemma licence on huggingface.co (signed in as the account that owns the worker's token), and say "accepted".

`ui.licence_needed` = his words, verbatim, short.

## Part E — phase 2 (after "accepted")

First confirm access was granted (same HEAD command): `200` → continue. `403`/`401` → wait and retry every 10 min for up to 1 h; still not `200` → mark phase 2 checks `blocked` with reason `awaiting HF approval (manual gate)`, leave the job queued (the Hub keeps re-checking) and reply. Record the HEAD results as `info.access_granted` `{attempts, final_code, minutes_after_accept}`.

Then `AP-4.1.md` **B5** with `WAIT_S=14400 QC_OUT=/tmp/ap41r3-p2.json`, log `/tmp/ap41r3-p2.log`, and the same checks as r2 Part E (`smoke.g_check_now`, `smoke.g_done`, `smoke.g_index`, `live.*`, `info.gate_wait_s`).

`AP-4.1-r3.json` `overall` = `pass` only if every non-`info`, non-`merge` check is `pass`.

## Part F — merge #7

Only if `OPS-HF1-r2.json` and `AP-4.1-r3.json` are both `overall` = `pass`: `gh pr ready 7 && gh pr merge 7 --merge`; `merge.pr7` = `{base: "main", merge_sha}`. Otherwise `merge.pr7` = `skip` with reason. Conflicts → finding, do not resolve.

## DOCUMENTS TO UPDATE (only these)

- `qc/OPS-HF1-r2.json`, `qc/AP-4.1-r3.json` (new).
- `docs/testing/AP-4.1-test-report.md`: "Manual acceptance" from r3.
- `docs/agent-context/PROJECT-STATE.md`: one session-log row per report; tick OPS-HF1 / AP-4.1 / MERGE-1 lines that now pass.
- `TODO.md` ("Active — Repo archive"): tick the matching lines.
- `CHANGELOG.md`: "QC r2 <overall>" under OPS-HF1, "QC r3 <overall>" under AP-4.1.
