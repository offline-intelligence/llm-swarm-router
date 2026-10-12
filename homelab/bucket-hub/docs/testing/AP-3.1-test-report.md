# AP-3.1 test report

## Run log

```bash
cd homelab/bucket-hub && PYTHONPATH=. uv run --with pytest pytest tests/ -q
```

| When | Result |
|------|--------|
| Before (AP-3 + ops PR #4) | 146 passed |
| After (AP-3.1) | 177 passed in 4.1s (PM run, Python 3.12, FastAPI 0.115.6) |

## Automated tests (new)

| File | Test | Asserts |
|------|------|---------|
| `test_repo_lane_ap31.py` | `test_aria2_lane_skips_repo_job_queued_ahead` | repo job ranked first, `lane: aria2` → torrent claimed (the starvation bug) |
| | `test_aria2_lane_skips_repo_while_clone_running` | two queued repo jobs ahead while one clone runs → torrent claimed |
| | `test_repo_lane_skips_torrent_queued_ahead` | `lane: repo` skips a torrent ranked first |
| | `test_lane_with_nothing_eligible_returns_none` | no job in lane → `null`, other jobs untouched |
| | `test_repo_meta_lane` | `lane: repo_meta` picks the sync job |
| | `test_no_body_keeps_legacy_any_lane_claim`, `test_empty_body_keeps_legacy_any_lane_claim` | old workers (no lane) behave as before |
| | `test_unknown_lane_rejected` | 400 |
| | `test_not_before_in_future_is_skipped`, `test_not_before_in_past_is_claimable` | TNAS back-off honoured by every claim |
| | `test_patch_stores_error_display_resolved_not_before` | Pi keeps `error_display`, `resolved`, `not_before` from the worker (were silently dropped) |
| | `test_running_clears_error_display_and_not_before` | stale defer text cleared when the job starts |
| | `test_raw_error_still_wins_over_stored_display` | real errors still shown |
| | `test_claim_next_sends_lane`, `test_main_loop_claims_pass_lanes` | worker sends lanes from every dispatch loop |
| | `test_gluetun_token_not_in_argv`, `test_gluetun_no_token_no_stdin` | token goes over stdin (`curl -H @-`), never argv |
| | `test_github_readme_fetch_decodes_base64` | `/readme` API fallback decodes content |
| `test_repo_archive_github.py` | `test_mount_offline_sets_backoff` | `not_before` = now + `HUB_REPO_DEFER_S`; nothing written |
| | `test_readme_fallback_when_archiver_writes_none` | old `:1` image path: API fallback writes `README.md`, excerpt filled |
| | `test_readme_fallback_failure_does_not_fail_job` | fallback error → job still `done` |
| `test_repo_archiver_image.py` | `test_pick_readme` (7 cases) | `README`, `Readme.MD`, `.rst`, `.adoc`, none |
| | `test_entry_mirror_and_readme_copy` | `git clone --mirror <url>`, LFS/prompt env, no submodules, `HEAD:README` copied as `README.md` (deferred AP-3 §T2) |
| | `test_docker_runner_argv_uses_gluetun_and_env_file` | `--network=container:gluetun`, `/work` mount, token only in 0600 env file, file deleted (deferred AP-3 §T2) |
| | `test_docker_runner_deletes_env_file_on_failure` | env file deleted on clone failure |

Round 2 (QC r1 F1: orphaned repo job after a worker restart). PM run: **183 passed**.

| File | Test | Asserts |
|------|------|---------|
| `test_repo_lane_ap31.py` | `test_recover_requeues_orphaned_repo_jobs` | `running`/`claimed` repo and repo_meta jobs re-queued with note, containers `hub-repo-partial-<id>` removed, aria2 jobs untouched |
| | `test_recover_skips_jobs_this_worker_runs` | jobs in `_repo_running` left alone |
| | `test_recover_returns_none_when_pi_unreachable` | `None` so `main()` retries |
| | `test_repo_claims_gated_on_recovery` | both repo claim sections wait for recovery |
| `test_repo_archiver_image.py` | `test_docker_runner_names_container_and_clears_leftover` | `docker rm -f hub-repo-partial-<id>` before `docker run --name hub-repo-partial-<id>` |
| | `test_remove_container_never_raises` | docker missing → `False` |

`test_deploy_manifest.py` now also checks `docker/repo-archiver/*` exist (added to `[worker]`).

## Manual acceptance (§T6 step 2, adversarial order)

Cursor runs `scripts/smoke-ap31-lanes.sh` after deploy (emits `QC {json}` lines + `QC_OUT` file); results go into `docs/pm/2026-10/qc/AP-3.1-r1.json` per `docs/pm/PM-CURSOR-PROTOCOL.md`, then summarised below.

| Step | Result |
|------|--------|
| Precheck `active_repo == 0` | **pass** (QC r1) |
| R1 long clone running | **pass** (`git/git` job `da8ff9d48de5`) |
| Torrent claimed ≤ 60 s while R1 runs | **pass** (10 s; Sintel magnet, `ext_movies` / `torrents`) |
| Torrent bytes rise while R1 runs | **pass** (~129 MB while R1 running) |
| R2, R3 finish after R1 | **fail** — 15 min drain window ended with Spoon-Knife still `running`, Hello-World `queued` (see `docs/pm/2026-10/qc/AP-3.1-r1.json`) |
| Hello-World `README.md` + non-empty `readme_excerpt` | **fail** — R3 not finished in smoke window; `git/git` archive on TNAS has `README.md` (manual spot-check) |
| `ps` on ai-server during smoke shows no `Authorization` in argv | **pass** (sampler output `0` only) |

## Round 2 (2026-10-12)

| Check | Result |
|-------|--------|
| Unit tests | **183 passed** |
| Deploy parity pi/worker | **pass** |
| Orphan recover log (74ad) | **skip/fail** — job already `error` before restart; **S4** job `27d1993819a1` shows `repo recover … container_removed=True` |
| Hello-World excerpt + TNAS README | **pass** (`b946a1e27485`) |
| S4 restart regression (`git/git`) | **pass** — named container removed, job `done`, README on TNAS |
| Full `smoke-ap31-lanes.sh` | **fail** — run1 stale Sintel dir; run2 R1 stuck `TNAS offline, will retry` |
| Token not in `ps` (1200 samples) | **pass** |

QC: `docs/pm/2026-10/qc/AP-3.1-r2.json` (**overall fail**).

## Round 3 (2026-10-12)

| Check | Result |
|-------|--------|
| Unit tests | **189 passed** (archiver branches+tags only) |
| Image `:3` + deploy parity | **pass** |
| `smoke.repos_drain` + Spoon-Knife | **pass** (1 MB `repo.git`, 0 `refs/pull`) |
| `smoke.torrent_bytes_rise` | **fail** (Tears of Steel bytes flat during R1) |
| Token not in `ps` (1200) | **pass** |
| TNAS defer / stale mount log | **none** in 30 min |

QC: `docs/pm/2026-10/qc/AP-3.1-r3.json` (**overall fail** — one smoke byte-rise check).

## Round 3 (PM fixes, 2026-10-12)

| Finding (r2) | Fix | Tests |
|--------------|-----|-------|
| F1 Spoon-Knife `error` (size limit) | `repo_archiver_entry.py`: bare repo, fetch heads + tags only, `HEAD` from `ls-remote --symref`; image `:3` | `test_entry_mirror_and_readme_copy` (argv), `test_entry_real_git_skips_pull_refs` (real git: `refs/pull/1/head` and its commit absent, `HEAD` = `trunk`, `Readme.md` copied) |
| F2 R1 stuck on `TNAS offline, will retry` | `repo_path_ready` re-check after `HUB_REPO_RECHECK_S`; `_recover_stale_mounts` clears a mount that answers `stat`; `path_ready` names a stale TNAS; defer note carries the reason; smoke `R1_WAIT_S=150` | `test_repo_path_ready_rechecks_before_defer`, `test_repo_path_ready_reports_second_reason`, `test_repo_path_ready_no_sleep_when_ready`, `test_stale_mount_cleared_when_responsive`, `test_stale_mount_kept_while_stat_hangs`, `test_mount_offline_defers` (note) |
| F3 Sintel collision | Handoff S0 `prep.torrent_dest_clean` | n/a |

Unit tests: **189 passed** (PM run, Python 3.13). Smoke script checked against a fake Hub with a TNAS defer on R1 for 8 s: 6/6 pass, `tnas_defer` recorded. Live QC: `docs/pm/2026-10/qc/AP-3.1-r3.json` (pending Cursor).
