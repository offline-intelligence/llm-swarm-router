# AP-5a.1 test report — per-download record (Pi journal API + ABOUT file)

**Branch:** `pm/ap-5a1` (on top of `99db36c`, the AP-4.2 / QC close-out). **Spec:** `docs/pm/2026-10/AP-5-index-architecture-v2.md` § Per-download record; split note in § Packets. **Operator doc:** `docs/DOWNLOAD-INDEX.md`. **Written by:** PM (2026-10-12).

## What changed

| File | Change |
|------|--------|
| `download_record.py` (new, Pi + worker) | merged journal view (entries, `note` and `deleted` events), byte-cursor export, `sources`, A6 search, context card, `ABOUT-THIS-DOWNLOAD.md` writer, delete-path matching |
| `app.py` | `/api/index/search`, `/export`, `/sources`, `POST /entries` (worker token), `GET /{id}`, `GET /{id}/card`, `PATCH /{id}` (note only). Finished jobs journal `segment`/`preset`/`saves_to`; housekeeping kinds (`storage_delete`, `sync`, scans) no longer get entries; Storage delete and cancel + purge append tombstones |
| `repo_archive_github.py` | `write_provenance_sidecar` also writes `ABOUT-THIS-DOWNLOAD.md` (GitHub and HF finalise both call it) |
| `scripts/rebuild-download-index.py` (new) | `--from-jobs DIR [--dry-run]` back-fill |
| `scripts/smoke-ap5a1-index.sh` (new) | X1–X7 |
| `scripts/deploy-manifest.txt` | `download_record.py` in `[pi]` and `[worker]`; back-fill script in `[pi]` |

## Behaviour changes to know about

- A finished Storage delete or Copy (sync) job no longer adds a "download" line to the journal. Before AP-5a.1 they did (noise).
- Deleting a folder through the Hub marks only records whose own folder is that path or inside it. Deleting a shared folder such as `torrents/` itself would mark every record that points at exactly that folder.
- Website copies do not get `ABOUT-THIS-DOWNLOAD.md` yet (their completion path has no index entry until AP-5c).

## Unit tests (PM)

`PYTHONPATH=. pytest tests/ -q` → **301 passed** (286 + 15 in `tests/test_download_record.py`).

| Spec id | Test |
|---------|------|
| I1 | `test_i1_last_line_wins_and_events_merge`, `test_i1_note_is_scrubbed` |
| I10 | `test_i10_from_jobs_dry_run_then_write` |
| I11 | `test_i11_storage_delete_tombstones_and_is_not_indexed`, `test_purge_complete_tombstones_job_entries`, `test_entries_under_matches_own_folder_not_parent` |
| I12 | `test_i12_provenance_writes_about_file` (GitHub/HF; website deferred to AP-5c) |
| I13 | `test_i13_tv_torrent_gets_no_sidecar`, `test_api_done_job_journal_has_segment_and_preset` |
| A6 API | `test_api_entry_card_note_export_sources`, `test_api_entries_requires_worker_token`, `test_export_cursor_returns_only_changed`, `test_sources_excludes_failed_and_deleted`, `test_search_and_terms_weights_and_deleted_filter`, `test_card_has_sections_and_no_secrets` |

## Manual acceptance (Cursor + Finn)

| Check | Result |
|-------|--------|
| Unit (integrator) r1 | **fail** — 300 passed, 1 failed (`test_entry_hf_error_kinds` / `GatedRepoError` needs `response=`) |
| Unit (integrator) r2 | **pass** — 301 passed (`huggingface_hub==0.26.2`); `test_repo_archive_hf.py` on 2.2.0 |
| Deploy + smoke X1–X7 r2 | **pass** — 7/7; X7 dry-run `to_write` 27 |
| Finn card (S3) | **not run** |

QC: `docs/pm/2026-10/qc/AP-5a1-r1.json` (**overall fail**); `docs/pm/2026-10/qc/AP-5a1-r2.json` (**overall pass**).
