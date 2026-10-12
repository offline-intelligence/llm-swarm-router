# AP-3.1 handoff, round 3: archiver refs fix, TNAS re-check, clean smoke (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC (`homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md`, schema `bucket-hub-qc/v1`). Do not edit application code, tests or `scripts/smoke-*.sh`. On a failing check: record a finding with `repro`, stop dependent steps, return the report.

OUTPUT: write `homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r3.json`, commit on `pm/ap-3.1`, push. Reply = that JSON in one ```json block first, then at most 5 lines.

## PM DIAGNOSIS OF ROUND 2 (input, do not re-litigate)

| finding | PM verdict | fix in round 3 |
|---------|-----------|----------------|
| r1 F1 orphan recovery | **Proven** by r2 S4 (job `27d1993819a1`: named container, `repo recover` line, re-queued, done with README). Not re-tested. | none |
| r2 F1 `74ad6f30004f` Spoon-Knife `error` (size limit) | **Real bug.** `git clone --mirror` copies GitHub `refs/pull/*`: every PR head, including fork commits. Spoon-Knife has tens of thousands of PRs, so the archive blew the smoke's 64 MB cap while the API `size` (branches only) looked tiny. | `repo_archiver_entry.py`: bare repo, fetch `+refs/heads/*` and `+refs/tags/*` only, `HEAD` set from `git ls-remote --symref`. Image **`bucket-hub-repo-archiver:3`**. Real-git unit test proves `refs/pull/*` are not archived. |
| r2 F2 R1 `queued` with `TNAS offline, will retry` | **Real fragility.** One failed mount check deferred the job for `HUB_REPO_DEFER_S` (120 s) and the smoke only waited 60 s. Also a mount that once timed out stayed in the worker's stale set while it was still mounted. | `hub-worker.py` `repo_path_ready`: re-check once after `HUB_REPO_RECHECK_S` (default 5) before deferring; stale mark cleared when the mount answers `stat` again; defer note now names the reason, e.g. `TNAS offline, will retry (NAS is not mounted)`. Smoke R1 waits `R1_WAIT_S` (150 s) and records any defer note. |
| r2 F3 Sintel collision | Test hygiene. | S0 below checks the torrent destination is clean before the smoke. |

## INPUT

| Key | Value |
|-----|-------|
| packet / round | `AP-3.1` / `3` |
| branch | `pm/ap-3.1`; PM commit `4842a71` on top of `d66d000` (same Mac checkout) |
| PR | https://github.com/offline-intelligence/llm-swarm-router/pull/5 (stays draft) |
| changed files | `docker/repo-archiver/repo_archiver_entry.py`, `hub-worker.py`, `repo_archive_github.py`, `scripts/smoke-ap31-lanes.sh`, 3 test files, `docs/REPO-ARCHIVE.md` |
| image | rebuild as **`bucket-hub-repo-archiver:3`** |
| Pi | `repo_archive_github.py` is worker-only; no Pi deploy needed this round (still run Pi parity) |
| round 1/2 jobs | not used; do not run checks against them |

## S0 prep

```bash
curl -s http://100.85.42.0:3000/api/jobs/74ad6f30004f | jq -c '{status, error, error_display, note: .progress.note}'
curl -s http://100.85.42.0:3000/api/repo-lane | jq -c .
ssh ai-server-ts 'ls -d /mnt/external/movies/torrents/Sintel* 2>/dev/null; true'
```

| id | expected |
|----|----------|
| `info.r2_f1_error_text` | always `pass`; `value` = the JSON line for `74ad6f30004f` (evidence for the PM diagnosis) |
| `prep.lane_idle` | `active_repo` = 0 |
| `prep.torrent_dest_clean` | no leftover folder for the torrent you will use. If one exists and it is from an AP-3.1 smoke, move it aside (`mv … …-ap31-old-$(date +%s)`, no `rm`) and record that in `deviations`; `value` = paths found |

## S1 integrate

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router && git switch pm/ap-3.1 && git log --oneline -3
git fetch offline-intelligence && git rebase offline-intelligence/main
cd homelab/bucket-hub && PYTHONPATH=. uv run --with pytest pytest tests/ -q 2>&1 | tee /tmp/ap31r3-unit.pytest.log | tail -3
cd ../.. && git push --force-with-lease offline-intelligence pm/ap-3.1
```

| id | expected |
|----|----------|
| `git.rebase` | exit 0, no `*.py`/`*.sh` conflicts |
| `unit.pytest` | `189 passed`, 0 failed (`git` must be on PATH: `test_entry_real_git_skips_pull_refs` must run, not skip) |
| `git.push` | PR #5 head = local `HEAD`; `value` = sha |

## S2 deploy worker

rsync the `[worker]` manifest set to `~/homelab/scripts/` (includes `docker/repo-archiver/`), then:

```bash
ssh ai-server-ts 'cd ~/homelab/scripts/docker/repo-archiver && docker build -t bucket-hub-repo-archiver:3 .'
```

**Finn** changes `REPO_ARCHIVER_IMAGE` to `bucket-hub-repo-archiver:3` in `~/homelab/scripts/hub-worker.env`. Mark `deploy.env_image` `blocked` until he confirms, then re-check. Then `ssh ai-server-ts 'systemctl --user restart hub-worker'`.

| id | expected |
|----|----------|
| `deploy.pi_parity` | `verify-deploy-parity.sh pi` exit 0 |
| `deploy.worker_parity` | `verify-deploy-parity.sh worker` exit 0 |
| `deploy.image_build` | `ssh ai-server-ts 'docker image inspect bucket-hub-repo-archiver:3 --format "{{.Id}}"'` exit 0; `value` = image id |
| `deploy.env_image` | `ssh ai-server-ts "grep -c '^REPO_ARCHIVER_IMAGE=bucket-hub-repo-archiver:3$' ~/homelab/scripts/hub-worker.env"` = `1` |
| `deploy.worker_service` | `is-active hub-worker` = `active` |
| `deploy.worker_log` | 120 s after restart: 0 lines matching `loop error\|Traceback\|hub http 4` once `Active Download not found` lines are removed; `value` = count |

## S3 full smoke, clean run (no restarts, env edits or manual job changes from here on)

Precondition: worker up for 2 min, `active_repo` = 0. Pick a small, well-seeded legal torrent (a different one from Sintel is fine). Start the sampler first, then the smoke:

```bash
# terminal A: 240 s, distinct counts of Authorization headers in process args
ssh ai-server-ts 'for i in $(seq 1 1200); do ps -eo args | grep -v grep | grep -c "Authorization: Bearer"; sleep 0.2; done | sort -u' \
  | tee /tmp/ap31r3-live.token_not_in_ps.log

# terminal B
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router/homelab/bucket-hub
TORRENT_URL='<magnet or .torrent>' DRIVE_ID='<id>' FOLDER_ID='<id>' QC_OUT=/tmp/ap31r3-smoke-qc.json \
  ./scripts/smoke-ap31-lanes.sh 2>&1 | tee /tmp/ap31r3-smoke.log
```

Run the smoke **once**. If it fails, do not re-run: return the report with the evidence below.

| id | expected |
|----|----------|
| `smoke.precheck` … `smoke.readme_excerpt` | copied unchanged from `QC_OUT`, all `pass`. `smoke.r1_running.value.tnas_defer` should be `""`; a non-empty value with `pass` is still a pass, but add a minor finding quoting it |
| `live.token_not_in_ps` | distinct counts = `0` only; `value` includes sample count (1200) |

## S4 archive content (after `smoke.repos_drain` passes)

```bash
for slug in octocat__Spoon-Knife octocat__Hello-World git__git; do
  ssh ai-server-ts "d=\$(ls -d /mnt/tnas/repo-archive/github-daily/*/$slug | tail -1); echo \$d; ls -A \$d; du -sm \$d/repo.git; \
    git --git-dir \$d/repo.git for-each-ref refs/pull | wc -l; git --git-dir \$d/repo.git symbolic-ref HEAD"
done
ssh ai-server-ts 'journalctl --user -u hub-worker --since "-30 min" | grep -E "repo path not ready|stale mount" | tail -20'
```

| id | expected |
|----|----------|
| `live.spoon_knife_done` | Spoon-Knife folder from today has `README.md`, `repo.git`, both sidecars, no `.partial-*`; `value` = `{names, size_mb}`; `size_mb` well under 64 |
| `live.no_pull_refs` | `refs/pull` count = `0` for all three; `value` = `{slug: count}` |
| `live.head_set` | `symbolic-ref HEAD` gives `refs/heads/<default branch>` for all three, matching the repo default branch from `GET https://api.github.com/repos/<owner>/<repo>` `.default_branch`; `value` = `{slug: ref}` |
| `info.tnas_recheck_log` | always `pass`; `value` = the grep lines (or `[]`) |

Afterwards dismiss the smoke torrent and add every job id this round created to `needs_finn` only if your tools cannot dismiss them.

## DOCUMENTS TO UPDATE (only these)

- `homelab/bucket-hub/docs/testing/AP-3.1-test-report.md`: add a "Round 3" table from the checks.
- `homelab/bucket-hub/docs/testing/AP-3-test-report.md`: §T6 step 2 and 3 status from `smoke.torrent_bytes_rise` and `live.spoon_knife_done`.
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`: if `overall` = `pass`, tick AP-3.1 and AP-3 §T6 step 2, mark AP-3 done; one session-log row citing `AP-3.1-r3.json`. Otherwise the session-log row only.
- `CHANGELOG.md`: one line under AP-3.1, "QC r3 <overall>".
- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r3.json` (new).

## needs_finn carried from round 2

Dismiss old smoke jobs if still visible: `cad3443a1297`, `86492e2d2519`, `f904ab85b909`, `7bd56f531143`, `66ebedadbce6`, `74ad6f30004f` (after S0 has read it).
