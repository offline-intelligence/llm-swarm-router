# AP-5a.2 test report: ai-server download catalogue

**Packet:** AP-5a.2 · **Branch:** `pm/ap-5a2` · **Spec:** `docs/pm/2026-10/AP-5-index-architecture-v2.md` · **Operator doc:** `docs/DOWNLOAD-INDEX.md` § Catalogue on ai-server

## Unit (PM, container, Python 3.13, SQLite with FTS5)

`PYTHONPATH=. python -m pytest -q`: **340 passed** (316 before; 24 new in `tests/test_hub_index.py`).

| id | test | proves |
|----|------|--------|
| I2 | `test_i2_grouping_and_skips`, `test_fs_group_rules` | `tv/<Show>`, `movies/<Film>`, `torrents/<release>`, repo-daily and HF folders become items; a Hub record owns the files under its folder; `repo.git` is one opaque entry; `@eaDir`, `.partial-*`, `.cache`, `.hub-*` skipped |
| I3 | `test_i3_missing_offline_and_back`, `test_i3b_empty_listing_of_big_root_is_not_a_mass_delete`, `test_incomplete_walk_marks_nothing_missing` | deleted on a mounted root → `missing`; unmounted → `offline` with rows kept, then `present` again; an empty or timed-out walk marks nothing missing |
| I4 | `test_i4_incremental_stats_only_changed_folders`, `test_i4_catalogue_reuses_unchanged_folders` | second scan = one stat per folder, no file stats; a changed folder re-stats only its own files |
| I5 | `test_i5_fts_and_semantics_ranking_and_file_hits` | every term must match; title beats README excerpt; note text found; file hits carry their item and `where`; FTS syntax in `q` is inert |
| I6 | `test_i6_token_required_and_no_secrets_in_output` | `/ingest` and `/rebuild` refuse a missing or wrong token; a row holding a token-shaped string is withheld from `/search` |
| I8 | `test_i8_snapshot_round_trip_through_the_pi` | snapshot `PUT` needs the worker token, rejects non-gzip, and the Pi-side reader finds an item by note text |
| I9 | `test_i9_overnight_step_calls_rebuild_over_ssh_within_its_limit` | the step runs `hub_index.py rebuild` over `ssh_ubuntu` with the worker env, inside `timeout_min`; failure raises |
| I11 | `test_i11_tombstone_marks_item_and_files_deleted`, `test_pi_nudges_hub_index_after_a_tombstone`, `test_purge_after_30_days` | a tombstone hides the item and marks its files `deleted`; the Pi nudges only when something was deleted; purge after 30 days |
| I14 | `test_i14_step_counts_reach_the_last_night_card` | `result_text` = `N new, N changed, N missing, N deleted` reaches the last-night card row |
| — | `test_journal_tail_cursor_and_reset`, `test_pi_fetch_falls_back_across_hub_urls`, `test_service_rebuild_health_item_and_nudge`, `test_subprocess_walker_matches_in_process`, `test_worker_nudge*`, `test_schedule_gains_the_step_once`, `test_manifest_and_unit`, `test_discover_roots` | cursor reset when the journal shrinks; HUB_URL fallback; HTTP service end to end; worker nudge only on `done`; schedule migration runs once; manifest and unit |

Load check (PM, container): 50 000 files in 1 202 folders, first scan 1.3 s, unchanged rescan 0.4 s, search 7–60 ms, catalogue 21 MB.

## Manual acceptance (Cursor)

| round | date | result | QC file |
|-------|------|--------|---------|
| r1 | 2026-10-13 | **fail** (smoke C5 Pi→ai-server SSH; C6 no machine_sleep in schedule) | `docs/pm/2026-10/qc/AP-5a2-r1.json` |
