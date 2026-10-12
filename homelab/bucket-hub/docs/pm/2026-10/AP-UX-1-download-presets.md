# AP-UX-1 — Download presets: the type picks the place, "Manually set path" overrides

**Status:** built by the PM on `pm/ap-ux-1`, 277 tests (2026-10-12); Cursor deploys after AP-4.1 QC r3 passes. See "As built" at the end.
**Depends on:** OPS-HF1 (gateway assets) deployed, so the Glance UI works. **Touches:** `app.py`, `form.html`, new `download_presets.py`, `capture-folders.json` handling, tests.

## Problem (Finn, 2026-10-12)

- The Download tab centres URL → **1 · Drive** → **2 · Folder** for every type, even where the server ignores the drive (`github_repo`, `huggingface_repo` write to the TNAS archive root). Finn sees "Media HDD → TV Show" next to a GitHub link and cannot tell where it will land.
- Finn wants media (torrents, films, video) visibly separate from repo archives.
- Destination defaults exist today, but in three unconnected places, and they disagree:

| Where | What it does today | Source |
|-------|--------------------|--------|
| `form.html` `applyTorrentCategoryDefaults` / `ensureTorrentShowFolder` | TV torrent → Expansion HDD (`ext_movies`/`movies_usb`) `torrents/`; film → `movies/` | client only |
| `form.html` archive-mode block | website copy → `nas`/`website_backups`, else `ext_movies`/`nas_staging` | client only |
| `app.py` `DEFAULT_TYPE_FOLDER_MAP` + `capture-folders.json` | Firefox capture / empty drive: video → `nas`/`media_archive`, magnet → `nas`/`inbox`, hf → `nas`/`ai_language` … | server (capture path only) |

So a magnet sent from the Firefox add-on lands in `nas/inbox`, while the same magnet queued from the form lands in the flat `torrents/` inbox that Sonarr watches (AP-1 decision). That inconsistency is a bug this packet removes.

## Decisions (PM defaults; Finn can override any row)

1. **One registry, server-side.** New `download_presets.py` (Pi) is the only place a type → destination rule lives. The form, the Firefox capture path, Requests (Lilly) approvals and API callers all resolve through it. `DEFAULT_TYPE_FOLDER_MAP` becomes the registry's fallback table; `capture-folders.json` stays as a per-install override of the registry.
2. **Preset by default, manual only on request.** A job without `manual_path: true` gets its destination from its preset; the server ignores any `drive_id`/`folder_id` sent alongside. With `manual_path: true` the job uses `drive_id`/`folder_id` exactly as today.
3. **Back-compat:** an old client that sends `drive_id` + `folder_id` and no `preset` is treated as manual (today's behaviour). A client that sends neither gets the preset for its detected kind (today's capture behaviour, now consistent).
4. **Film torrents use the same flat inbox as TV** (`torrents/` on the Expansion HDD); Radarr imports into `movies/`. Today the form picks `movies/` directly, which bypasses the inbox rule. Cursor confirms Radarr's download-client path matches `torrents/` before deploy (check `R0` below); if it does not, the film preset keeps `movies/` and this row is revisited.
5. **The Hub never invents `Show/Season` folders** (AP-1 decision stands): presets only pick an existing inbox or library folder.
6. **Existing connections keep working** (Finn, 2026-10-12). AP-UX-1 changes only where the Hub *sends* new jobs. It does not edit Sonarr, Radarr, aria2, Jellyfin, Jackett or Firefox add-on config, and does not move existing files or jobs. Queued and running jobs keep their stored destination. R0 reads the current Sonarr and Radarr download-client paths and Jellyfin library paths before deploy and again after; any difference is a blocker.

## Segments (Finn, 2026-10-12)

Finn asked for separate download segments, each with pre-defined paths, built on the existing downloaders. Each preset belongs to one **segment**; the segment is stored on the job (`segment`), shown in the queue (filter chips "All · TV & film · Repo archive · Websites · Other"), and carried into the index (AP-5).

| Segment | Presets | Existing machinery it reuses (unchanged) |
|---------|---------|------------------------------------------|
| `tv` — TV & film | `tv`, `film` | aria2 lane in Gluetun, flat `torrents/` inbox, Sonarr/Radarr import, Jellyfin tags |
| `repo` — Repo archive | `github_repo`, `hf_repo`, `hf_files` | repo lane, archiver image, TNAS `repo-archive/` root, gate flow (AP-4.1) |
| `website` — Websites | `website` | website archive (httrack / FlareSolverr) |
| `other` — Other | `video`, `file` | MeTube/yt-dlp via Proton, aria2 direct download |

No new downloader is built: a segment is a name plus its presets' paths, and every preset resolves to a job kind the worker already runs.

## Preset registry v1

| id | Segment | Label (chip) | Job kind(s) | Destination | Fallback | "Saves to" line |
|----|-------|--------------|-------------|-------------|----------|-----------------|
| `tv` | TV & film | TV episode or season | `magnet`, `http` (.torrent) | Expansion HDD (`ext_movies`/`movies_usb`) › `torrents/` | none | "Expansion HDD › torrents (Sonarr files it under TV)" |
| `film` | TV & film | Film | `magnet`, `http` (.torrent) | Expansion HDD › `torrents/` | none | "Expansion HDD › torrents (Radarr files it under Films)" |
| `video` | Other | Video (YouTube etc.) | `video` | `nas` › `media_archive` | Media HDD › `videos/` if present | "TNAS › media_archive" |
| `file` | Other | File (direct link) | `http` | `nas` › `inbox` | Media HDD › `inbox/` | "TNAS › inbox" |
| `github_repo` | Repo archive | GitHub repo | `github_repo` | TNAS archive root `github-daily/<day>/` | none (job defers while TNAS sleeps) | "TNAS repo archive › github-daily" |
| `hf_repo` | Repo archive | Hugging Face model or dataset | `huggingface_repo` | TNAS archive root `huggingface-daily/<day>/` | none (defers) | "TNAS repo archive › huggingface-daily" |
| `hf_files` | Repo archive | Hugging Face: selected files | `hf` | `nas` › `ai_language` | none | "TNAS › ai_language (selected files only)" |
| `website` | Websites | Website copy | `website_archive` | `nas` › `website_backups` | Expansion HDD › `nas_staging` | "TNAS › website_backups" |

Drive ids are matched the way the form does today (`resolveMoviesExpansionDriveId`: id `ext_movies`/`movies_usb`, or root `/mnt/external/movies`), moved server-side as `resolve_drive(role)`. Roles: `expansion_movies`, `nas`, `media_hdd`, `archive_root`.

**Auto-pick:** on paste the server suggests a preset from the URL: `_detect_kind` (`github.com` → `github_repo`, `huggingface.co` → `hf_repo`, `magnet:`/`.torrent` → `tv` unless the torrent search category is `movies` → `film`, YouTube/known video hosts → `video`, other `http(s)` → `file`). Search results carry their preset (torrent category, GitHub/HF provider). The user can switch chip before queueing.

## API

| Method | Path | Behaviour |
|--------|------|-----------|
| `GET` | `/api/presets` | `{presets: [{id, group, label, kinds, available, resolved: {drive_id, folder_id, path, label} \| {archive_root: "…"} \| null, reason, saves_to}]}` resolved against the current `library.json` (mounted / present flags). `available: false` + `reason` ("Expansion HDD is not mounted on the worker") when no candidate works |
| `POST` | `/api/presets/resolve` | Body `{url, preset?, torrent_category?}` → `{preset, kind, destination, saves_to, available, reason}`. No job is created. Used by the form on paste and by the smoke script |
| `POST` | `/api/jobs` | New optional fields `preset` (id) and `manual_path` (bool). Rules in "Decisions" 2–3. Stored on the job: `preset`, `segment`, `destination_source` (`"preset"` \| `"manual"` \| `"legacy"`). An unavailable preset → **503** with the reason (never a silent fallback to another drive than the table allows) |

`POST /api/capture` (Firefox) and the Requests approve path call the same resolver; `capture-folders.json` overrides are applied as `{preset_id: {drive_id, folder_id}}` (the old `type_folder_map` keys are mapped: `media`/`video` → `video`, `magnet` → `tv`, `http` → `file`, `hf` → `hf_files`, `website` → `website`, `github` → `github_repo`).

## UI (`form.html`)

1. **Download tab, top to bottom:** URL box → preset chips in four segments ("TV & film: TV · Film", "Repo archive: GitHub · Hugging Face", "Websites: Website copy", "Other: Video · File") → one line **Saves to: …** from `saves_to` → **Queue download**.
2. **1 · Drive** and **2 · Folder** are hidden. A **Manually set path** checkbox under the Saves-to line reveals them; while it is ticked the request sends `manual_path: true` and the Saves-to line reads "Manual: <drive> › <folder>". Unticking restores the preset.
3. An unavailable preset shows its chip disabled with the reason as hint text, and Queue is disabled unless Manually set path is ticked.
4. The **Type** select in More options is removed (presets replace it). "Select files" in the HF panel switches the preset to `hf_files`.
5. Search results queue with their preset; the confirmation toast names the destination ("Queued to Expansion HDD › torrents").
6. Every new dynamic value goes through `escHtml`/`escAttr` (extend `test_form_escaping.py`). Bump the Glance `?v=` and deploy the `[gateway]` section.

## Tests (PM writes; `tests/test_download_presets.py`, extend `tests/test_form_escaping.py`)

| id | case | expected |
|----|------|----------|
| P1 | each preset resolves against a fixture `library.json` with every drive mounted | destination per the table; `saves_to` text |
| P2 | Expansion HDD unmounted | `tv`/`film` `available: false` with reason; `POST /api/jobs {preset:"tv"}` → 503 |
| P3 | `nas` folder `website_backups` absent | `website` falls back to `nas_staging` |
| P4 | `manual_path: true` + drive/folder | job uses them; `destination_source: "manual"` |
| P5 | preset + stray `drive_id` without `manual_path` | drive ignored; `destination_source: "preset"` |
| P6 | old client: `drive_id` + `folder_id`, no preset | today's behaviour; `destination_source: "legacy"` |
| P7 | no drive, no preset, magnet URL | preset `tv` (not `nas/inbox`) |
| P8 | capture path with `capture-folders.json` override for `video` | override wins |
| P9 | `POST /api/presets/resolve` for a GitHub, HF, magnet, YouTube and plain https URL | presets `github_repo`, `hf_repo`, `tv`, `video`, `file`; no job file written |
| P10 | archive-root presets | no drive needed; `destination.archive_root` = `HUB_REPO_ARCHIVE_ROOT` |
| P11 | UI escaping | new render functions pass `test_innerhtml_interpolations_escaped` |
| P13 | every preset has a segment; `POST /api/jobs` stores `segment`; `GET /api/jobs?segment=tv` filters | as stated |
| P12 | UI structure | `#drives`/`#folders` sit inside the manual-path container that is hidden by default |

## Live acceptance (Cursor, `scripts/smoke-apux1-presets.sh`, no downloads)

| id | check |
|----|-------|
| R0 | Read-only, before and after deploy: Radarr and Sonarr download-client paths (`/api/v3/downloadclient`) and Jellyfin library paths; Radarr path = Expansion HDD `torrents/` (else film keeps `movies/`); before = after. No key printed |
| R0b | Existing queued/running jobs keep `destination_path` unchanged after deploy (compare `GET /api/jobs` before/after) |
| R1 | `GET /api/presets`: every preset `available` (or a reason naming an offline drive) |
| R2 | `POST /api/presets/resolve` for 5 sample URLs → expected presets |
| R3 | `POST /api/jobs {preset:"hf_repo"}` for the tiny test model → `done` "Already archived" (no download) |
| R4 | manual override job to a test folder with `manual_path: true` → `destination_source: "manual"`, then cancel |
| R5 | Finn: the Download tab shows preset chips and Saves-to, no drive chips until Manually set path is ticked |

## Out of scope

- Per-show folder creation (stays with Sonarr).
- New drives or folder creation flows (unchanged, behind Manually set path).
- Index/search (AP-5).


## As built (PM, 2026-10-12)

- Built as specced, with these decisions:
  - **Firefox "Website" capture keeps saving the single page** (preset `file`, tag `website`). A full website copy is a bigger job (unlimited depth by default), so it stays a deliberate choice in the Hub's Websites segment.
  - Firefox "GitHub" / "Hugging Face" captures use the repo archive presets (`github_repo`, `hf_repo`), consistent with the Repo archive segment.
  - Requests: link mode no longer requires a drive (preset decides); approving a note re-resolves the destination from the link's preset. This also fixes approving a GitHub/HF link, which used to get `worker: aria2`.
  - A preset that does not fit the link (YouTube with `tv`, a non-GitHub URL with `github_repo`) → 400 "does not look like a … link".
  - Queue panel: segment filter chips; the choice is remembered per browser.
- **Finding:** `aria2_dir_for()` maps an Expansion HDD `movies/` destination to `/mnt/torrents/movies` (host `torrents/movies/`), because aria2 only mounts the torrents inbox. Film torrents never landed in `movies/` directly; the `film` preset makes the flat inbox explicit.
- Tests and local checks: `docs/testing/AP-UX-1-test-report.md`. Smoke: `scripts/smoke-apux1-presets.sh` (PHASE=before / after).
