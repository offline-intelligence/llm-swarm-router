# AP-3.1 handoff, round 1: integrate, deploy, QC (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). The PM (Claude) wrote the code. You do not edit application code, tests or `scripts/smoke-*.sh`. If a check fails: record it, stop that branch of work, continue only with independent checks, return the QC report. The PM fixes and sends round 2.

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (read it first; schema `bucket-hub-qc/v1`).

OUTPUT (mandatory, machine-readable):
1. Write `homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r1.json` (schema above), commit it on `pm/ap-3.1`, push.
2. Your reply to Finn = that JSON in one ```json block, first thing, nothing before it. After it, at most 5 lines of prose.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md`
2. `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`
3. `homelab/bucket-hub/docs/testing/AP-3.1-test-report.md`
4. `homelab/bucket-hub/docs/REPO-ARCHIVE.md`
5. `homelab/bucket-hub/scripts/smoke-ap31-lanes.sh`, `scripts/deploy-manifest.txt`

## INPUT

| Key | Value |
|-----|-------|
| packet | `AP-3.1` |
| round | `1` |
| branch | `pm/ap-3.1` (local only; PM commits `e4ba81c` + protocol commit on top of `a2f5523`) |
| target | `offline-intelligence/main` |
| pi | `stackrise-pi` (`100.85.42.0`), app `~/homelab/hub-form/`, service `hub-form` |
| worker | `ai-server-ts`, scripts `~/homelab/scripts/`, service `hub-worker` |
| image | `bucket-hub-repo-archiver:2`, context `~/homelab/scripts/docker/repo-archiver` |
| hub api | `http://100.85.42.0:3000` |

## CHANGE SUMMARY (for the PR body; do not re-implement)

- `POST /api/jobs/claim` optional `{"lane": "aria2"|"video"|"repo"|"repo_meta"|"archive"|"exclusive"|"other"}`; worker loops pass their lane. No body = legacy claim.
- `not_before` on jobs; every claim skips future values; TNAS defer sets now + `HUB_REPO_DEFER_S` (120).
- `JobUpdate` accepts `error_display`, `resolved`, `not_before`.
- `gluetun_http_json`: `Authorization` via stdin (`docker run -i`, `curl -H @-`).
- Archiver `:2`: any-name README → `README.md`; worker API fallback `/repos/{o}/{r}/readme`.
- `docker/repo-archiver/*` in `[worker]` manifest. Tests 146 → 177.

## STEPS AND CHECKS

Run in order. Each step names the check ids it produces. Save each command's full output to `/tmp/ap31-<check-id>.log`.

### S1 integrate

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
git fetch offline-intelligence
git switch pm/ap-3.1
git rebase offline-intelligence/main
cd homelab/bucket-hub && PYTHONPATH=. uv run --with pytest pytest tests/ -q 2>&1 | tee /tmp/ap31-unit.pytest.log | tail -3
cd ../.. && git push -u offline-intelligence pm/ap-3.1
```

Open a **draft** PR `pm/ap-3.1` → `main`, title `AP-3.1: lane-aware claim, TNAS back-off, README fix`, body = CHANGE SUMMARY + link to the test report.

| id | expected |
|----|----------|
| `git.rebase` | exit 0; conflicts only in `*.md` (list them in `git.rebase_conflicts`); any conflict in `*.py`/`*.sh` → `fail`, stop |
| `unit.pytest` | `177 passed`, 0 failed; `value` = summary line; failing node ids in a finding |
| `git.pr_draft` | PR URL in `value` and `git.pr_url` |

Stop all later steps if `unit.pytest` fails.

### S2 deploy Pi (first; old worker must keep working)

rsync the `[pi]` manifest set to `~/homelab/hub-form/`, restart `hub-form` per `05-OPERATIONS-SSH-DEPLOY.md` (system unit `sudo systemctl restart hub-form` or user unit `systemctl --user restart hub-form.service`, whichever is live; record which in `evidence`).

| id | expected |
|----|----------|
| `deploy.pi_service` | `is-active` for the live `hub-form` unit = `active` |
| `deploy.pi_parity` | `./scripts/verify-deploy-parity.sh pi` exit 0 |
| `deploy.pi_old_worker_ok` | 120 s after restart: `ssh ai-server-ts 'journalctl --user -u hub-worker --since "-2 min" --no-pager'` has 0 lines matching `hub http 4|loop error`; `value` = match count |

### S3 deploy worker

rsync the `[worker]` manifest set to `~/homelab/scripts/` (includes `docker/repo-archiver/`), then build:

```bash
ssh ai-server-ts 'cd ~/homelab/scripts/docker/repo-archiver && docker build -t bucket-hub-repo-archiver:2 .'
```

**Finn** sets `REPO_ARCHIVER_IMAGE=bucket-hub-repo-archiver:2` in `~/homelab/scripts/hub-worker.env`. Mark `deploy.env_image` `blocked` until he confirms, then re-check. Then `ssh ai-server-ts 'systemctl --user restart hub-worker'`.

| id | expected |
|----|----------|
| `deploy.image_build` | `ssh ai-server-ts 'docker image inspect bucket-hub-repo-archiver:2 --format "{{.Id}}"'` exit 0; `value` = image id |
| `deploy.env_image` | `ssh ai-server-ts "grep -c '^REPO_ARCHIVER_IMAGE=bucket-hub-repo-archiver:2$' ~/homelab/scripts/hub-worker.env"` = `1` |
| `deploy.worker_service` | `ssh ai-server-ts 'systemctl --user is-active hub-worker'` = `active` |
| `deploy.worker_parity` | `./scripts/verify-deploy-parity.sh worker` exit 0 |
| `deploy.worker_log` | 120 s after restart, same `journalctl --user` command: 0 lines matching `hub http 4|loop error|Traceback`; `value` = count; attach last 30 lines as `log` |

### S4 acceptance smoke (§T6 step 2, adversarial order)

Pick a small, well-seeded legal torrent and the Expansion HDD torrents inbox ids (`curl -s http://100.85.42.0:3000/api/library`). Start the ps sampler on ai-server **first**, then the smoke:

```bash
# terminal A: sample for 240 s, print distinct counts of Authorization headers in process args
ssh ai-server-ts 'for i in $(seq 1 1200); do ps -eo args | grep -v grep | grep -c "Authorization: Bearer"; sleep 0.2; done | sort -u' \
  | tee /tmp/ap31-live.token_not_in_ps.log

# terminal B
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router/homelab/bucket-hub
TORRENT_URL='<magnet or .torrent>' DRIVE_ID='<id>' FOLDER_ID='<id>' QC_OUT=/tmp/ap31-smoke-qc.json \
  ./scripts/smoke-ap31-lanes.sh 2>&1 | tee /tmp/ap31-smoke.log
```

Copy the six `smoke.*` objects from `/tmp/ap31-smoke-qc.json` into `checks` unchanged. If `smoke.torrent_claimed_60s` fails with evidence starting `torrent errored`, change the torrent and re-run once; report both runs (`deviations`).

| id | expected |
|----|----------|
| `smoke.precheck` … `smoke.readme_excerpt` | as emitted by the script (`pass`) |
| `live.token_not_in_ps` | sampler output is exactly `0` (no line ≥ 1); `value` = distinct counts |
| `live.tnas_readme_file` | `ssh ai-server-ts 'ls -la /mnt/tnas/repo-archive/<download_dir from smoke.readme_excerpt>/'` lists `README.md`, `repo.git`, `.hub-provenance-*`, `.hub-tags-*`, no `.partial-*`; `value` = file names |

Afterwards cancel or dismiss the smoke torrent in the Hub UI.

## DOCUMENTS TO UPDATE (only these)

- `homelab/bucket-hub/docs/testing/AP-3.1-test-report.md` → fill "Manual acceptance" from the QC checks.
- `homelab/bucket-hub/docs/testing/AP-3-test-report.md` → §T6 step 2 and step 3 status = result of `smoke.torrent_bytes_rise` and `live.tnas_readme_file`, link the QC file.
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md` → if `overall` = `pass`: tick AP-3.1, AP-3 §T6 step 2, mark AP-3 done; add one session-log row citing the QC file. If not: one session-log row only.
- `CHANGELOG.md` → append "Deployed 2026-10-12, QC r1 <overall>" under the AP-3.1 entry.
- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r1.json` (new).
