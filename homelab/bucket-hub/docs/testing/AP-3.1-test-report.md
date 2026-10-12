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

`test_deploy_manifest.py` now also checks `docker/repo-archiver/*` exist (added to `[worker]`).

## Manual acceptance (§T6 step 2, adversarial order)

Cursor runs `scripts/smoke-ap31-lanes.sh` after deploy (emits `QC {json}` lines + `QC_OUT` file); results go into `docs/pm/2026-10/qc/AP-3.1-r1.json` per `docs/pm/PM-CURSOR-PROTOCOL.md`, then summarised below.

| Step | Result |
|------|--------|
| Precheck `active_repo == 0` | |
| R1 long clone running | |
| Torrent claimed ≤ 60 s while R1 runs | |
| Torrent bytes rise while R1 runs | |
| R2, R3 finish after R1 | |
| Hello-World `README.md` + non-empty `readme_excerpt` | |
| `ps` on ai-server during a metadata call shows no `Authorization` | |
