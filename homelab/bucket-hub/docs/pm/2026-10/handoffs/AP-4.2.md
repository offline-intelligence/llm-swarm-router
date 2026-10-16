# AP-4.1 r3 finish + AP-UX-1 r2 close + AP-4.2 r1 (Cursor prompt)

Paste everything below the line into Cursor. Parts A and B can run now. Part C waits until Part A has `smoke.g_done` (no worker restart while the Gemma download runs).

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). You do not edit application code, tests, `Caddyfile`, `glance.yml` or `scripts/smoke-*.sh`. Failing check → finding with `repro`, stop dependent steps, continue with independent ones. Never print a token or API key; env checks are counts only.

PM DECISIONS (from Finn's paste, 2026-10-12 ~19:46 AEST):
1. **AP-4.1 r3: resume phase 2 now.** Do not wait for the new schedule. Finn accepted both licences; Gemma job `7407b085aa83` was already `running`. A job that is already running or done when B5 starts is a pass for the AP-4.1 goal (the Hub picked access up by itself), so `smoke.g_check_now` may be `skip` with that reason.
2. **`gate.state = awaiting_licence` while running** is a cosmetic bug (gate was only cleared on done). The UI already hid it (it filters on `queued`). Fixed in AP-4.2 with a `granted` state.
3. **AP-UX-1 r2 closes on Finn's own one-line R5** plus your r2 evidence; no r3. Sonarr/Radarr R0 (`/ping` → 000) becomes a separate ops item **OPS-ARR1**, not an AP-UX-1 blocker.
4. **AP-4.2** = Finn's re-check schedule: gaps 1 min, 5 min, 30 min, then hourly (cumulative 1, 6, 36, 96 … min), Check now kept, copy split "Licence needed" (auto) / "Approval needed" (manual). Spec `docs/pm/2026-10/AP-4.2-gate-schedule.md`. Branch `pm/ap-4.2` (local, on top of `pm/ap-ux-1@a4376b1`).

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (`bucket-hub-qc/v1`).

OUTPUT: update `qc/AP-4.1-r3.json` (final), update `qc/AP-UX-1-r2.json` (final), new `qc/AP-4.2-r1.json`. Each committed on its own branch and pushed. Reply = the three JSONs in their own ```json blocks, then at most 5 lines. If Finn is needed, reply with the partial JSONs and wait.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/2026-10/AP-4.2-gate-schedule.md`
2. `homelab/bucket-hub/docs/testing/AP-4.2-test-report.md` ("Behaviour changes")
3. `homelab/bucket-hub/docs/pm/2026-10/handoffs/AP-4.1.md` (B5, S4 disk checks) and `handoffs/OPS-HF1-r2-AP-4.1-r3.md` (Parts E, F)

## Part A — AP-4.1 r3 phase 2 (branch `pm/ap-4.1`)

```bash
curl -s http://100.85.42.0:3000/api/jobs/7407b085aa83 | jq -c '{status, gate, note: .progress.note, download_dir}'
```

- `queued` with a gate → run Part E of `OPS-HF1-r2-AP-4.1-r3.md` unchanged.
- `running` or `done` → record `info.access_granted` = `{final_code: "n/a (job already past gate)", status_at_resume}` and `smoke.g_check_now` = `skip` ("access granted before phase 2; the scheduled re-check picked it up"). Then run `PHASE=2 WAIT_S=14400 QC_OUT=/tmp/ap41r3-p2.json ./scripts/smoke-ap41-gate.sh` for `smoke.g_done` / `smoke.g_index` (ignore its own `g_check_now` result, say so in `deviations`), then the `live.*` disk checks and `info.gate_wait_s`.
- Also record `info.llama_job` = `{status, gate.state, gate.checks}` of `038317edec3d` (read only; Part C acts on it).

`overall` = `pass` if every non-`info`, non-`merge` check is `pass` (a `skip` on `g_check_now` for the reason above counts as pass). Then Part F of `OPS-HF1-r2-AP-4.1-r3.md` (merge #7 only if `OPS-HF1-r2.json` and `AP-4.1-r3.json` both pass).

## Part B — AP-UX-1 r2 close (branch `pm/ap-ux-1`)

Ask Finn in chat for **one line in his own words** confirming the Download tab on `http://100.85.42.0:3000/` (segment chips, Saves to line, Manually set path, queue segment filter, magnet → Expansion HDD › torrents). `ui.presets` = his words, verbatim. Move the Sonarr/Radarr R0 note to `deviations` as "OPS-ARR1: *arr /ping 000 on worker host; R0 compared Jellyfin only".

If `overall` = `pass`: `gh pr ready 8`. If #7 is merged by then: `gh pr edit 8 --base main` (conflicts → finding, do not resolve), wait for checks, `gh pr merge 8 --merge`; `merge.pr8` = `{base, merge_sha}`. Otherwise `merge.pr8` = `skip` with reason.

## Part C — AP-4.2 r1 (branch `pm/ap-4.2`; only after Part A `smoke.g_done` is final)

### C0 git + unit

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
git checkout pm/ap-4.2 && git log --oneline -3
cd homelab/bucket-hub && PYTHONPATH=. python3 -m pytest -q 2>&1 | tail -1
git push -u offline-intelligence pm/ap-4.2
gh pr create --draft --base pm/ap-ux-1 --title "AP-4.2: HF access re-check schedule" --body-file docs/testing/AP-4.2-test-report.md
```

(Base `main` instead if #8 is already merged; rebase onto `main` first, conflicts → finding.)

| id | expected |
|----|----------|
| `unit.pytest` | `286 passed` (or more), 0 failed |
| `git.push` / `git.pr` | pushed; draft PR url |

### C1 env check (counts only)

```bash
ssh ai-server-ts 'grep -c "^HF_GATE_RECHECK_S=" ~/homelab/scripts/hub-worker.env; grep -c "^HF_GATE_SCHEDULE_S=" ~/homelab/scripts/hub-worker.env'
```

`info.gate_env` = `{recheck_lines, schedule_lines}`. If `recheck_lines` > 0, the old fixed gap still wins: **stop Part C after C2** and ask Finn to delete that line (he edits env, not you), then continue.

### C2 deploy (worker + Pi + gateway)

Precondition: `active_repo` = 0 on the worker (no repo job running). Then as earlier rounds: rsync `[worker]`, restart `hub-worker`; rsync `[pi]`, `systemctl --user restart hub-form.service`; gateway `glance.yml` (`?v=20261012g42`; diff must be `?v=` only).

| id | expected |
|----|----------|
| `deploy.worker_parity` / `deploy.pi_parity` / `deploy.gateway_parity` | exit 0 each |
| `deploy.worker_service` | `active`, 0 errors in the first 2 min of the log |
| `deploy.pi_app_reloaded` | process start later than `app.py` mtime |
| `deploy.form_gate_copy` | `curl -s http://100.85.42.0:3000/hub-form/ \| grep -c "Approval needed\|Next automatic check in"` ≥ 2 |

### C3 live schedule check (no download)

Pick a gated repo the worker token has **not** accepted. Candidates (PM-unverified; check each with the HEAD command from AP-4.1 r3, stdin token): `mistralai/Mistral-7B-Instruct-v0.3`, `bigcode/starcoder2-15b`, `google/shieldgemma-2b`. Use the first that returns 401/403. None → `smoke.s_schedule` = `blocked` with the codes.

```bash
id=$(curl -s -X POST http://100.85.42.0:3000/api/jobs -H 'Content-Type: application/json' \
  -d "{\"url\":\"https://huggingface.co/$REPO\",\"preset\":\"hf_repo\",\"title\":\"ap42-smoke\",\"tags\":[\"ap42-smoke\"],\"options\":{\"max_size_mb\":500}}" | jq -r .job.id)
for t in 30 100; do sleep $t; curl -s http://100.85.42.0:3000/api/jobs/$id | jq -c '{status, state: .gate.state, checks: .gate.checks, since: .gate.since, next_check: .gate.next_check}'; done
curl -s -X POST http://100.85.42.0:3000/api/jobs/$id/gate-check | jq -c '{next_check: .job.gate.next_check}'
sleep 30; curl -s http://100.85.42.0:3000/api/jobs/$id | jq -c '{checks: .gate.checks, next_check: .gate.next_check}'
```

| id | expected |
|----|----------|
| `smoke.s_first_gap` | at ~30 s: `checks` 1, `next_check` − `since` ≈ 60 s (± 15) |
| `smoke.s_second_gap` | at ~130 s: `checks` 2, `next_check` ≈ check-2 time + 300 s (± 15) |
| `smoke.s_check_now` | after Check now + 30 s: `checks` 3, next gap ≈ 1800 s |

Then cancel and dismiss the job.

### C4 Llama job

```bash
curl -s -X POST http://100.85.42.0:3000/api/jobs/038317edec3d/gate-check | jq -c '{ok}'
```

Wait up to 2 min. `info.llama_after` = `{status, gate.state}`: `running`/`done` means Finn's accept worked; still `awaiting_licence` means HF has not granted it yet (record, not a blocker). While it is `running`, `gate.state` must be `granted` → `smoke.s_granted_state` = pass (or `skip` if it never ran).

### C5 Finn checks (UI)

Ask Finn, on `http://100.85.42.0:3000/` (hard refresh), while the C3 job is still waiting (run C5 before cancelling it): the card says **Approval needed** or **Licence needed** with "Next automatic check in N min", and the bar reads "Waiting for Hugging Face access (1)". `ui.gate_copy` = his words, verbatim, short.

`AP-4.2-r1.json` `overall` = `pass` only if every non-`info` check is `pass`.

## DOCUMENTS TO UPDATE (only these)

- `qc/AP-4.1-r3.json`, `qc/AP-UX-1-r2.json` (final), `qc/AP-4.2-r1.json` (new).
- `docs/testing/AP-4.1-test-report.md`, `AP-UX-1-test-report.md`, `AP-4.2-test-report.md`: "Manual acceptance".
- `docs/agent-context/PROJECT-STATE.md`: one session-log row per report; tick the AP-4.1 / AP-UX-1 / AP-4.2 / MERGE lines that now pass.
- `TODO.md`: tick matching lines.
- `CHANGELOG.md`: "QC r3 <overall>" under AP-4.1, "QC r2 <overall>" under AP-UX-1, "Deployed 2026-10-12, QC r1 <overall>" under AP-4.2.
