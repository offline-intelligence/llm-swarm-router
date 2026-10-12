# Cursor prompt: finish AP-4 QC (r1b), then integrate AP-4.1 (gated HF licences)

Paste everything below the line into Cursor. It answers Cursor's last status message ("Ask PM: issue AP-4 QC r1 resume handoff") and adds AP-4.1.

---

PM → Cursor, 2026-10-12. Reply to your AP-3.1 / AP-4 status message.

- **AP-3.1:** closed, accepted. PR #5 waits for Finn's merge. Nothing to do.
- **AP-4 QC r1:** accepted as blocked on env only (F1). Your env fix (`REPO_ARCHIVER_IMAGE=…:4`, with Finn's OK) is accepted. Resume as **round 1b** (Part A). Your `info.legacy_hf_lfs` result (real weights, not pointers) corrects my inference; noted in PROJECT-STATE.
- **Pi restart:** `sudo systemctl restart hub-form` failed in r1, so the Pi may still run the old `app.py` even though parity passed. Part A S1 finds the real service and proves the reload.
- **Finn's HF licence note:** specced and implemented as **AP-4.1** (Part B). Finn chose **one click**: a gated job waits with an Accept licence button and downloads by itself after he accepts. No auto-accept, no HF session cookie stored.

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). The PM wrote all code, tests and smoke scripts. You do not edit application code, tests or `scripts/smoke-*.sh`. On a failing check: record a finding with `repro`, stop dependent steps, continue only with independent checks, return the report. The PM fixes and sends the next round.

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (schema `bucket-hub-qc/v1`). Two reports this time: `AP-4-r1b.json` (Part A) and `AP-4.1-r1.json` (Part B).

REPLY: both JSON reports, each in its own ```json block (Part A first), then at most 5 lines. If Part A is not `pass`, return Part A only.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md`
2. `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md` (decisions dated 2026-10-12, incl. "HF gated models" and "Pi restart command unknown")
3. `homelab/bucket-hub/docs/pm/2026-10/handoffs/AP-4-r1b.md` (Part A, run as written)
4. `homelab/bucket-hub/docs/pm/2026-10/handoffs/AP-4.md` (S3/S4 reused by r1b)
5. `homelab/bucket-hub/docs/pm/2026-10/AP-4.1-hf-gated-access.md` (spec; A1–A3, A5 built; A4/S1 not built)
6. `homelab/bucket-hub/docs/testing/AP-4.1-test-report.md`
7. `homelab/bucket-hub/docs/REPO-ARCHIVE.md` ("Hugging Face" and "Gated models" sections)
8. `homelab/bucket-hub/docs/agent-context/05-OPERATIONS-SSH-DEPLOY.md`

## INPUT

| Key | Value |
|-----|-------|
| Part A branch | `pm/ap-4` (local head `5288074`, 2 commits ahead of the remote: r1b handoff + AP-4.1 spec) |
| Part B branch | `pm/ap-4.1` (PM commits on top of `pm/ap-4`; the Mac checkout is on it now) |
| PRs | #5 `pm/ap-3.1` (Finn merges), #6 `pm/ap-4` draft base `pm/ap-3.1`; new draft PR for `pm/ap-4.1` with **base `pm/ap-4`** |
| image | `bucket-hub-repo-archiver:4` (unchanged in Part B; do not rebuild) |
| env (Finn) | Part B needs `HF_TOKEN` (HF read token, same account Finn uses in the browser) in `~/homelab/scripts/hub-worker.env` on ai-server-ts. Optional: `HF_GATE_RECHECK_S` (600), `HF_GATE_MAX_WAIT_H` (168); leave unset |
| gated test model (Finn) | `GATE_REPO` = org/name of a gated model Finn has **not** accepted yet. Verify before use (Part B S3) |

## Part A — AP-4 QC round 1b

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
git switch pm/ap-4
```

Run `homelab/bucket-hub/docs/pm/2026-10/handoffs/AP-4-r1b.md` exactly as written (S1 Pi reload, S2 worker restart, S2b URL detection, S3 smoke, S4 disk checks, its DOCUMENTS TO UPDATE). Write `homelab/bucket-hub/docs/pm/2026-10/qc/AP-4-r1b.json`, commit on `pm/ap-4`, `git push offline-intelligence pm/ap-4`.

**Gate:** continue to Part B only if `AP-4-r1b.json` `overall` = `pass`. Otherwise stop and reply with Part A only.

## Part B — AP-4.1 round 1

### B1 integrate

```bash
git switch pm/ap-4.1
git rebase pm/ap-4            # picks up your r1b QC commit; expect no conflicts (docs only)
cd homelab/bucket-hub && PYTHONPATH=. uv run --with pytest --with huggingface_hub==0.26.2 pytest tests/ -q 2>&1 | tee /tmp/ap41r1-unit.pytest.log | tail -3
cd ../.. && git push -u offline-intelligence pm/ap-4.1
gh pr create --draft --repo offline-intelligence/llm-swarm-router --head pm/ap-4.1 --base pm/ap-4 \
  --title "AP-4.1: gated Hugging Face repos wait for a one-click licence" --body-file homelab/bucket-hub/docs/testing/AP-4.1-test-report.md
```

| id | expected |
|----|----------|
| `git.rebase` | exit 0, no conflicts |
| `unit.pytest` | `239 passed`, 0 failed, 0 skipped |
| `git.push` | remote `pm/ap-4.1` = local `HEAD`; `value` = sha |
| `git.pr` | draft PR URL, base `pm/ap-4` |

### B2 env (Finn) and deploy

1. **Finn** adds `HF_TOKEN=<read token>` to `~/homelab/scripts/hub-worker.env`. You only check presence, never print the value: `ssh ai-server-ts "grep -c '^HF_TOKEN=hf_' ~/homelab/scripts/hub-worker.env"`. Mark `deploy.env_hf_token` `blocked` until it is `1`.
2. Pi: rsync the `[pi]` manifest set (as in r1), then restart with the command `AP-4-r1b.json` recorded in `deploy.pi_service`. Reload Glance.
3. Worker: rsync `[worker]`, then `ssh ai-server-ts 'systemctl --user restart hub-worker'`.

| id | expected |
|----|----------|
| `deploy.pi_parity` | `verify-deploy-parity.sh pi` exit 0 |
| `deploy.worker_parity` | `verify-deploy-parity.sh worker` exit 0 |
| `deploy.env_hf_token` | `1` (value never printed or logged) |
| `deploy.pi_app_reloaded` | Pi process start time later than `~/homelab/hub-form/app.py` mtime (same method as r1b) |
| `deploy.gate_endpoint` | `curl -s -o /dev/null -w '%{http_code}' -X POST http://100.85.42.0:3000/api/jobs/does-not-exist/gate-check` = `404` with body `{"detail":"Job not found"}` (an old `app.py` has no such route and answers `{"detail":"Not Found"}`) |
| `deploy.form_gate_ui` | `curl -s http://100.85.42.0:3000/hub-form/ \| grep -c 'queueLicenceBar\|data-gate-check'` ≥ 2 |
| `deploy.worker_service` | `active` |
| `deploy.worker_log` | 120 s after restart: 0 lines matching `loop error\|Traceback\|hub http 4` |

### B3 pick and verify the gated model (Finn names it)

Ask Finn for `GATE_REPO`: a gated model he has **not** accepted, ideally small (under ~5 GB of safetensors) and instantly approved. Verify from the Mac (public metadata, no token):

```bash
curl -s "https://huggingface.co/api/models/$GATE_REPO?blobs=true" | jq -c '{id, gated, sha, n: (.siblings|length), st_bytes: ([.siblings[]|select(.rfilename|endswith(".safetensors"))|.size]|add)}'
```

| id | expected |
|----|----------|
| `info.gate_repo` | `gated` = `"auto"` (if `"manual"`, ask Finn for another; record both). `value` = the jq output |

### B4 live smoke, phase 1 (no restarts or env edits from here to the end of B5)

Precondition: worker up 2 min, `active_repo` = 0. Start the token sampler from r4/r1b (`grep -c "hf_"`, 1200 × 0.2 s) in the background now; it must cover phase 2.

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router/homelab/bucket-hub
PHASE=1 GATE_REPO="$GATE_REPO" QC_OUT=/tmp/ap41r1-p1.json ./scripts/smoke-ap41-gate.sh 2>&1 | tee /tmp/ap41r1-p1.log
```

Expected `smoke.gate_precheck`, `smoke.gate_check_404`, `smoke.g_waiting`, `smoke.g_waiting_stable` = `pass`. The log ends with `ACTION Finn: open <url>, accept the licence, then run PHASE=2`.

Then **stop and ask Finn, in chat**, to:
1. Open the Hub queue and confirm he sees the job with **Licence needed**, an **Accept licence** button and the "Waiting for a licence (1)" bar.
2. Click Accept licence, agree on huggingface.co, and say "accepted".

| id | expected |
|----|----------|
| `ui.licence_needed` | Finn confirms all three UI items (`value` = his words, verbatim, short) |

### B5 phase 2 and disk checks (after Finn says "accepted")

```bash
PHASE=2 QC_OUT=/tmp/ap41r1-p2.json ./scripts/smoke-ap41-gate.sh 2>&1 | tee /tmp/ap41r1-p2.log
```

Expected `smoke.g_check_now`, `smoke.g_done`, `smoke.g_index` = `pass`. Then run the AP-4.md S4 commands against the job's `download_dir`, with ids:

| id | expected |
|----|----------|
| `live.hf_layout` | `snapshot/`, `README.md`, both sidecars |
| `live.hf_real_weights` | largest file > 10 000 bytes, LFS grep count `0` |
| `live.no_partials` | `0` |
| `live.index_rows` | tail includes `huggingface_repo` / `archived` / `hf:model/<GATE_REPO>` with `licence_accepted_by` = `user` |
| `live.token_not_in_ps` | sampler distinct counts = `0` only |

Afterwards dismiss the smoke jobs (`JOBS` line). Leave the archived model on TNAS.

## DOCUMENTS TO UPDATE (only these)

Part A: as listed in `AP-4-r1b.md`.

Part B:
- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-4.1-r1.json` (new).
- `homelab/bucket-hub/docs/testing/AP-4.1-test-report.md`: fill "Manual acceptance".
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`: one session-log row citing `AP-4.1-r1.json`; if `overall` = `pass`, tick the AP-4.1 backlog line.
- `homelab/bucket-hub/TODO.md`: if `pass`, tick "AP-4.1 gated HF licences" under "Active — Repo archive".
- `CHANGELOG.md`: one line under the AP-4.1 entry, "Deployed 2026-10-12, QC r1 <overall>".

Commit Part B docs on `pm/ap-4.1` and push.
