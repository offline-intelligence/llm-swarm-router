# AP-UX-1 test report — download presets and segments

**Branch:** `pm/ap-ux-1` (on top of `pm/ap-4.1`). **Spec:** `docs/pm/2026-10/AP-UX-1-download-presets.md`. **Written by:** PM (2026-10-12).

## What changed

| File | Change |
|------|--------|
| `download_presets.py` (new, Pi) | Registry of 8 presets in 4 segments (TV & film · Repo archive · Websites · Other); `resolve()` against `library.json` with fallbacks and `capture-folders.json` overrides; `suggest()` from a URL; `job_kind_for()`; `segment_for_kind()` for old jobs |
| `app.py` | `GET /api/presets`, `POST /api/presets/resolve`; `POST /api/jobs` takes `preset` + `manual_path` and stores `preset`, `segment`, `destination_source` (`preset` / `manual` / `legacy`), `saves_to`; unavailable preset → 503 with the reason; `GET /api/jobs?segment=`; every job in the API carries `segment`. Firefox capture, Requests link mode and Requests approve now resolve through presets |
| `form.html` | Download type chips grouped by segment, "Saves to" line, **Manually set path** reveals Drive/Folder; Type select removed; toast names the destination; queue panel segment filter (All · TV & film · Repo archive · Websites · Other) |
| `glance.yml` | iframe `?v=20261012ux1` |
| `scripts/deploy-manifest.txt` | `download_presets.py` in `[pi]` |
| `scripts/smoke-apux1-presets.sh` (new) | R0 (connections unchanged), R0b (existing jobs unchanged), R1–R4; no real downloads |

## Behaviour changes to know about

- A bare magnet from Firefox now lands in the flat `torrents/` inbox (same as the form). Before: `nas/inbox`.
- Firefox "GitHub" and "Hugging Face" captures now use the repo archive (`github_repo` / `huggingface_repo`). Before: a drive clone to `nas/inbox` or `nas/ai_language`.
- Firefox "Website" still saves the single page (preset File, tag `website`), not a full site copy.
- Approving a Request with a GitHub/HF link now routes to the repo lane (before: `worker: aria2`, a latent bug).
- PM finding: `aria2_dir_for()` already maps an Expansion HDD `movies/` destination to `/mnt/torrents/movies`, i.e. `torrents/movies/` on the host. So film torrents never reached `movies/` directly; the film preset making `torrents/` explicit changes no path Radarr sees except that subfolder (R0 records Radarr's paths).

## Round 2 fix (PM, after QC r1)

QC r1 `smoke.r4_manual` failed with HTTP 400 because the `tv` preset resolved to **TNAS inbox**, not Expansion HDD `torrents/`. Cause: the shipped `capture-folders.json` maps `magnet` → `nas/inbox`, and `load_overrides()` imported that legacy key as a `tv` override (same for `website` → `nas/inbox`). So the r1 "Behaviour changes" line about magnets was not true live. R1 passed because it only checked `available`.

- `tv` and `film` are now `fixed`: always Expansion HDD `torrents/` (where Sonarr/Radarr import), capture-folders.json cannot move them.
- Legacy `magnet` and `website` keys are no longer imported (`website` meant "direct file found on a web page"; the File preset already defaults to `nas/inbox`).
- Smoke R1 now fails if tv/film are not `/mnt/external/movies/torrents` or website is not `website_backups` / `nas_staging`.
- New tests `test_p8_repo_capture_folders_keeps_tv_film_website_defaults`, `test_p8_fixed_presets_ignore_explicit_override`. **279 passed.**

## Unit tests (PM)

`PYTHONPATH=. pytest tests/ -q` → **277 passed** (241 before + 33 in `tests/test_download_presets.py` + 3 in `tests/test_form_escaping.py`). `test_pi_legacy_hf_keeps_drive_path` updated: an `hf` job with no drive now gets 503 from the `hf_files` preset instead of 400 "Unknown drive" (an unknown drive id still gives 400).

| Spec id | Test |
|---------|------|
| P1 | `test_p1_each_preset_resolves` (6 cases), `test_p1_every_preset_has_a_known_segment` |
| P2 | `test_p2_expansion_unmounted` |
| P3 | `test_p3_website_falls_back_to_staging`, `test_p3_tnas_asleep_video_falls_back_to_media_hdd` |
| P4 | `test_p4_manual_path` |
| P5 | `test_p5_preset_ignores_stray_drive` |
| P6 | `test_p6_old_client_drive_and_folder` |
| P7 | `test_p7_bare_magnet_uses_tv_inbox`, `test_p7_movies_category_picks_film`, `test_p7_capture_magnet_matches_form` |
| P8 | `test_p8_capture_folders_override`, `test_p8_override_ignored_for_archive_root` |
| P9 | `test_p9_resolve_endpoint` (5 URLs), `test_p9_list_endpoint` |
| P10 | `test_p10_archive_root_presets` |
| P11 | `test_innerhtml_interpolations_escaped[presetChip]`, `[renderPresetChips]` |
| P12 | `test_p12_drive_and_folder_hidden_behind_manual_path` |
| P13 | `test_p13_segment_stored_and_filtered`, `test_p13_old_jobs_get_a_segment` |
| — | `test_preset_rejects_wrong_link`, `test_capture_github_goes_to_repo_archive`, `test_capture_website_keeps_single_page`, `test_request_link_without_drive_uses_preset`, `test_approve_note_moves_to_preset`, `test_approve_github_link_goes_to_repo_lane` |

## PM local checks

- Headless Chromium against a local Hub with a fixture library: 8 chips in 4 groups; GitHub URL → "Saves to: TNAS repo archive › github-daily"; magnet → "Expansion HDD › torrents (Sonarr files it under TV)"; queue toast names the destination; Drive/Folder hidden until Manually set path; queue segment filter shows only matching jobs; 0 console errors.
- `smoke-apux1-presets.sh` against the local Hub: R0b, R1, R2, R4 pass; R0 and R3 fail as expected (no ai-server, no worker). R0's snapshot code was run against a fake Sonarr/Radarr/Jellyfin: API-key fields are filtered out.

## Manual acceptance (Cursor + Finn)

| id | result |
|----|--------|
| R0 | **pass** (Jellyfin paths; Radarr/Sonarr ConnectionResetError) |
| R0b | **pass** (1 active job unchanged) |
| R1 | **pass** (8/8 presets available) |
| R2 | **pass** (5/5 resolve) |
| R3 | **pass** (hf_repo job done) |
| R4 | **fail** (manual tv → nas/inbox HTTP 400; needs /mnt/media on worker) |
| R5 (Finn) | **blocked** — `escAttr is not defined` on queue (OPS-HF1); review on Tailscale `http://100.85.42.0:3000/` after gateway fix |

QC: `docs/pm/2026-10/qc/AP-UX-1-r1.json` (**overall fail**: gateway Caddy parity, R4). Finn live notes: `docs/pm/2026-10/handoffs/PM-PASTE-2026-10-12-ui-blocker-ops-hf1.md`.

### QC r2 (2026-10-12)

| id | result |
|----|--------|
| R0 | **pass** (Jellyfin; *arr ConnectionResetError unchanged) |
| R0b | **pass** (2 jobs unchanged) |
| R1 | **pass** (8/8; tv/film → `/mnt/external/movies/torrents`) |
| R2 | **pass** (5/5) |
| R3 | **pass** (`7d639ca70123` hf_repo done) |
| R4 | **pass** (manual tv → `torrents/`) |
| R5 (Finn) | **pass** — integrator browser QC forwarded by Finn; PM accepted 2026-10-12 |

QC: `docs/pm/2026-10/qc/AP-UX-1-r2.json` (**overall pass**).
