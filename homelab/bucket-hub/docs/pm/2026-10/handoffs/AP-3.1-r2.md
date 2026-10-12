# AP-3.1 handoff, round 2: orphan recovery, re-deploy, QC (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC (`homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md`, schema `bucket-hub-qc/v1`). Do not edit application code, tests or `scripts/smoke-*.sh`. On a failing check: record a finding with `repro`, stop dependent steps, return the report.

OUTPUT: write `homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r2.json`, commit on `pm/ap-3.1`, push. Reply = that JSON in one ```json block first, then at most 5 lines.

## PM DIAGNOSIS OF ROUND 1 (input, do not re-litigate)

| finding | PM verdict | fix in round 2 |
|---------|-----------|----------------|
| F1 `smoke.repos_drain` | **Real bug.** The worker restart mid-smoke (r1 deviation 4) killed the Spoon-Knife thread. The Pi kept job `74ad6f30004f` as `running`, so `active_repo` stayed 1 and `b946a1e27485` (Hello-World) could never be claimed. No recovery existed for repo-lane jobs. | `hub-worker.py` `recover_orphaned_repo_jobs()`: at startup (retried until the Pi answers, repo claims gated on it) every `running`/`claimed` repo or repo_meta job not owned by this process is re-queued with note `Re-queued after worker restart`, and its container `hub-repo-partial-<id>` is removed. `repo_runner.py` names each archiver container and removes a leftover before a new run. |
| F2 `smoke.readme_excerpt` | Consequence of F1 (R3 never ran). README path itself proven on `git__git` (spot check). Script evidence text was misleading. | Script now reports `R3 (Hello-World) not done` when that is the cause. |
| F4 `live.tnas_readme_file` | Consequence of F1. | none |
| F3 `deploy.worker_log` | Not AP-3.1. `Active Download not found for GID` = stale aria2 gid on the smoke torrent after the restart (known pain: Retry vs Resume). Backlogged under P2. | Check now excludes that one message and reports its count separately (`info.aria2_stale_gid`). |
| deviation 4 (restart mid-smoke) | Invalidates a smoke run. | Rule below: no restarts or env edits after S3 finishes; if one happens, re-run S5 from scratch. |

## INPUT

| Key | Value |
|-----|-------|
| packet / round | `AP-3.1` / `2` |
| branch | `pm/ap-3.1`; PM commit on top of `78494cc` (same Mac checkout; no rebase needed unless `main` moved) |
| PR | https://github.com/offline-intelligence/llm-swarm-router/pull/5 (stays draft) |
| changed files | `hub-worker.py`, `repo_runner.py`, `scripts/smoke-ap31-lanes.sh`, `tests/test_repo_lane_ap31.py`, `tests/test_repo_archiver_image.py`, docs |
| image | `bucket-hub-repo-archiver:2` unchanged (no rebuild) |
| existing jobs | `74ad6f30004f` (Spoon-Knife, orphaned `running`), `b946a1e27485` (Hello-World, `queued`), `18d0343be5f5` (smoke torrent) |

## S1 integrate

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router && git switch pm/ap-3.1 && git log --oneline -3
git fetch offline-intelligence && git rebase offline-intelligence/main
cd homelab/bucket-hub && PYTHONPATH=. uv run --with pytest pytest tests/ -q 2>&1 | tee /tmp/ap31r2-unit.pytest.log | tail -3
cd ../.. && git push --force-with-lease offline-intelligence pm/ap-3.1
```

| id | expected |
|----|----------|
| `git.rebase` | exit 0, no `*.py`/`*.sh` conflicts |
| `unit.pytest` | `183 passed`, 0 failed |
| `git.push` | PR #5 head = local `HEAD`; `value` = sha |

## S2 deploy (Pi then worker; both manifest sets, `repo_runner.py` is in both)

Before restarting the worker, record the state of the orphan: `curl -s http://100.85.42.0:3000/api/jobs/74ad6f30004f | jq -c '{status, note: .progress.note}'` (expect `running`).

| id | expected |
|----|----------|
| `deploy.pi_parity` | `verify-deploy-parity.sh pi` exit 0 (after Pi rsync + `hub-form` restart) |
| `deploy.worker_parity` | `verify-deploy-parity.sh worker` exit 0 (after worker rsync, before restart is fine) |
| `deploy.worker_service` | after `ssh ai-server-ts 'systemctl --user restart hub-worker'`: `is-active` = `active` |
| `deploy.worker_log` | 120 s after restart: `journalctl --user -u hub-worker --since "-2 min"` has 0 lines matching `loop error\|Traceback\|hub http 4` once lines containing `Active Download not found` are removed; `value` = count |
| `info.aria2_stale_gid` | always `pass`; `value` = count of `Active Download not found` lines in the same window |

## S3 orphan recovered (live proof of the F1 fix, uses the round 1 jobs)

| id | expected |
|----|----------|
| `live.recover_log` | worker log after restart has `repo recover 74ad6f30004f (github_repo, was running, container_removed=…)`; `value` = that line |
| `live.orphan_requeued` | within 60 s of restart `74ad6f30004f` is no longer `running` with note `Cloning…`; `value` = status + note seen |
| `live.lane_drains` | within 10 min both `74ad6f30004f` and `b946a1e27485` are `done`; `value` = `{id, status, note}` for each |
| `live.hello_readme_excerpt` | `curl -s …/api/jobs/b946a1e27485 \| jq -r '.index_entry.readme_excerpt'` non-empty; `value` = first 40 chars |
| `live.tnas_readme_file` | `ssh ai-server-ts "ls -la /mnt/tnas/repo-archive/$(curl -s …/api/jobs/b946a1e27485 \| jq -r .download_dir)/"` lists `README.md`, `repo.git`, `.hub-provenance-*`, `.hub-tags-*`, no `.partial-*`; `value` = names |

If `live.lane_drains` fails, stop and return the report with `journalctl` lines for both job ids and `ssh ai-server-ts 'docker ps -a --filter name=hub-repo- --format "{{.Names}} {{.Status}}"'`.

## S4 deliberate restart (regression test for F1)

```bash
curl -s -X POST http://100.85.42.0:3000/api/jobs -H 'Content-Type: application/json' \
  -d '{"kind":"github_repo","url":"https://github.com/git/git","title":"git/git","source":"manual","tags":["github","ap31-r2"],"options":{"refresh":true,"max_size_mb":1024}}' | jq -r .job.id
# wait until that job is "running", then:
ssh ai-server-ts 'docker ps --filter name=hub-repo- --format "{{.Names}}"'      # expect hub-repo-partial-<id>
ssh ai-server-ts 'systemctl --user restart hub-worker'
# within 60 s:
ssh ai-server-ts 'docker ps -a --filter name=hub-repo-partial-<id> --format "{{.Names}} {{.Status}}"'
```

| id | expected |
|----|----------|
| `live.restart_container_named` | before restart `docker ps` shows `hub-repo-partial-<id>` |
| `live.restart_requeued` | after restart the job shows note `Re-queued after worker restart` or is already `running` again with a new `started_at`; `value` = observed |
| `live.restart_no_duplicate` | at no point two `hub-repo-partial-<id>` containers; `value` = `docker ps -a` output |
| `live.restart_job_done` | the job reaches `done` within 15 min, folder has `README.md`, no `.partial-*` |

## S5 full smoke, clean run (no restarts or env edits from here on)

Precondition: `GET /api/repo-lane` `active_repo` = 0 and the worker has been up for 2 min. Cancel the round 1 smoke torrent `18d0343be5f5` first if your tools allow it; otherwise add it to `needs_finn`.

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router/homelab/bucket-hub
TORRENT_URL='<magnet or .torrent>' DRIVE_ID='<id>' FOLDER_ID='<id>' QC_OUT=/tmp/ap31r2-smoke-qc.json \
  ./scripts/smoke-ap31-lanes.sh 2>&1 | tee /tmp/ap31r2-smoke.log
```

Run the token sampler from round 1 in parallel for the full 240 s (1200 samples), not shorter.

| id | expected |
|----|----------|
| `smoke.precheck` … `smoke.readme_excerpt` | copied unchanged from `QC_OUT`, all `pass` |
| `live.token_not_in_ps` | distinct sampler counts = `0` only; `value` includes sample count (must be 1200) |

## DOCUMENTS TO UPDATE (only these)

- `homelab/bucket-hub/docs/testing/AP-3.1-test-report.md`: add "Round 2" table from the checks.
- `homelab/bucket-hub/docs/testing/AP-3-test-report.md`: §T6 step 2 + 3 status from `smoke.torrent_bytes_rise` and `live.tnas_readme_file`.
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`: if `overall` = `pass`, tick AP-3.1 and AP-3 §T6 step 2, mark AP-3 done; one session-log row citing `AP-3.1-r2.json`.
- `CHANGELOG.md`: one line under AP-3.1, "QC r2 <overall>".
- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r2.json` (new).
