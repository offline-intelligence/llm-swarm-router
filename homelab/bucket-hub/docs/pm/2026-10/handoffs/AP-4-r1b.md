# AP-4 handoff, round 1b: resume QC r1 (restart + smoke only) (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). Round 1b resumes AP-4 QC r1 from where it blocked (F1, `deploy.env_image`). **No code changes, no redeploy of files, no image rebuild.** You do not edit application code, tests or `scripts/smoke-*.sh`. On a failing check: record a finding with `repro`, stop dependent steps, continue only with independent checks, return the report.

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (schema `bucket-hub-qc/v1`).

OUTPUT: write `homelab/bucket-hub/docs/pm/2026-10/qc/AP-4-r1b.json` (new file; leave `AP-4-r1.json` as it is), commit on `pm/ap-4`, push. Reply = that JSON in one ```json block first, then at most 5 lines.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md`
2. `homelab/bucket-hub/docs/pm/2026-10/handoffs/AP-4.md` (round 1: S3 and S4 are reused unchanged below)
3. `homelab/bucket-hub/docs/pm/2026-10/qc/AP-4-r1.json` (what already passed)
4. `homelab/bucket-hub/docs/agent-context/05-OPERATIONS-SSH-DEPLOY.md`

## INPUT

| Key | Value |
|-----|-------|
| packet / round | `AP-4` / `1b` |
| branch / PR | `pm/ap-4` / #6 (draft, base `pm/ap-3.1`; do not retarget in this round) |
| carried from r1 | `unit.pytest`, `git.*`, `deploy.pi_parity`, `deploy.worker_parity`, `deploy.image_build`, `deploy.image_hf_version`, `deploy.form_kinds`, `info.*`: copy into r1b with `"evidence": "carried from AP-4-r1.json"` |
| env | `REPO_ARCHIVER_IMAGE=bucket-hub-repo-archiver:4` set by Cursor with Finn's OK after r1. `HF_TOKEN` unset (fine: smoke model is public) |

## S1 Pi app reload (r1 deviation: `sudo systemctl restart hub-form` said "unit not found")

`form.html` is read per request, but `app.py` / `job_kinds.py` / `index_writer.py` only change on process restart. AP-4's drive-check and URL-detection changes live in `app.py`, so the smoke is only valid once the Pi process is newer than the deployed `app.py`.

```bash
ssh stackrise-pi 'systemctl --user list-units --all | grep -iE "hub|glance"; sudo systemctl list-units --all | grep -iE "hub|glance"; docker ps --format "{{.Names}} {{.Status}}" 2>/dev/null | grep -iE "hub|glance"; pgrep -af "uvicorn|app.py"'
```

Restart whatever serves `~/homelab/hub-form/app.py` (user unit, system unit or container, as found). Record the exact command in `deviations` and in `value`.

| id | expected |
|----|----------|
| `deploy.pi_service` | `value` = `{how: "<unit/container>", restart_cmd: "…"}`; restart exit 0 |
| `deploy.pi_app_reloaded` | process start time (`ps -o lstart= -p <pid>`) is later than `stat -c %y ~/homelab/hub-form/app.py`; `value` = both times |

## S2 worker restart (after S1)

```bash
ssh ai-server-ts "grep -c '^REPO_ARCHIVER_IMAGE=bucket-hub-repo-archiver:4$' ~/homelab/scripts/hub-worker.env"
ssh ai-server-ts 'systemctl --user restart hub-worker && sleep 120 && systemctl --user is-active hub-worker && journalctl --user -u hub-worker --since "-2min" --no-pager | grep -cE "loop error|Traceback|hub http 4" || true'
```

| id | expected |
|----|----------|
| `deploy.env_image` | `1` (closes F1) |
| `deploy.worker_service` | `active` |
| `deploy.worker_log` | `0` matching lines in the 120 s after restart |

## S2b URL detection (after the worker restart, so the new worker handles the job)

```bash
D=$(curl -s -X POST http://100.85.42.0:3000/api/jobs -H 'Content-Type: application/json' -d '{"url":"https://huggingface.co/hf-internal-testing/tiny-random-gpt2","title":"ap4-r1b-detect","source":"manual","tags":["ap4-smoke"],"options":{"max_size_mb":500}}')
echo "$D" | jq -c '{kind: .job.kind, id: .job.id, destination_path: .job.destination_path}'
# poll GET /api/jobs/<id> every 10 s until status is done or error (max 15 min)
```

| id | expected |
|----|----------|
| `deploy.pi_kind_detect` | no `kind` in the body, yet `.job.kind` = `huggingface_repo` and the job reaches `done` (or `error` with a readable `error_display`, which is a finding). `value` = `{kind, id, status, note}`. Wait for it to finish before S3 so the smoke precheck sees `active_repo` = 0. The smoke's H1 uses `refresh` and H2 expects the dedupe, so this job does not disturb it |

## S3 smoke and S4 disk checks

Run **S3** and **S4** from `AP-4.md` exactly as written (same commands, same check ids), with `QC_OUT=/tmp/ap4r1b-smoke-qc.json` and logs to `/tmp/ap4r1b-smoke.log`. No restarts or env edits from the start of S3. Run the `live.token_not_in_ps` sampler only if `HF_TOKEN` is set; otherwise `skip` with reason `HF_TOKEN unset`.

Afterwards dismiss the smoke jobs (`JOBS` line in the smoke log) if your tools allow.

## overall

`pass` only if every non-`info` check is `pass` (the token sampler may be `skip`). A smoke failure is a finding for the PM, not something to retry until green: one smoke run, unless a check fails for a clearly external reason (huggingface.co unreachable), in which case one re-run is allowed and both runs go in `evidence`.

## DOCUMENTS TO UPDATE (only these)

- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-4-r1b.json` (new).
- `homelab/bucket-hub/docs/testing/AP-4-test-report.md`: "Manual acceptance" rows from r1b.
- `homelab/bucket-hub/docs/testing/AP-3-test-report.md`: §T6 step 6 from `live.hf_real_weights`.
- `homelab/bucket-hub/docs/agent-context/05-OPERATIONS-SSH-DEPLOY.md`: replace the Pi restart line with the command that actually worked in S1.
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`: one session-log row citing `AP-4-r1b.json`; tick AP-4 only if `overall` = `pass`.
- `CHANGELOG.md`: one line under the AP-4 entry, "QC r1b <overall>".
