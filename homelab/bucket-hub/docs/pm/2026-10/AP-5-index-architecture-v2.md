# AP-5 v2 — Searchable index of everything on the NAS and HDDs (ai-server catalogue)

**Status:** architecture spec (PM, 2026-10-12). It **revises** `cursor-github-hf-downloader.md` §A6 "Storage" and "API" and splits AP-5 into AP-5a/5b/5c. The record schema (§A6 "Record schema (v1)"), `index_writer.py`, `secret_scan` and context-card wording stay as specced.
**Depends on:** OPS-HF1 deployed. Independent of AP-UX-1 (either order works; PM order puts presets first).

## What Finn asked for (2026-10-12)

1. One Hub area to text-search **everything** on the TNAS and the HDDs: repos, models, media, websites. Not only things the Hub downloaded.
2. The search index is cached on ai-server's local system SSD, updated after **each completed download** and after the **nightly sync**, instead of scanning remote JSONL on every query.

The original §A6 only indexed Hub downloads, with the primary copy on the Pi. That cannot answer "is *The Office* S03 on any drive?" for files that arrived outside the Hub, and a Pi scan of NAS paths would be slow and would wake drives.

## One source of truth

> **The files on disk, plus the Hub's per-item records, are the truth. The ai-server catalogue is a derived cache that can always be rebuilt from them. Nothing is written only to the catalogue.**

| Layer | Where | Written by | Role |
|-------|-------|-----------|------|
| Files + sidecars | TNAS (`/mnt/tnas/...`), Media HDD (`/mnt/media`), Expansion HDD (`/mnt/external/movies`) | downloads; `.hub-provenance-<id>.json` (repos), completion sidecars (torrents), `.hub-index-<id>.json` (video/website, AP-5c) | **truth** for "what exists and where" |
| Download journal | Pi `$JOBS_DIR/download-index.jsonl` (all kinds) + TNAS `repo-archive/download-index.jsonl` (repos) | `app.py` on job finish; worker after repo finalise; note edits (append, last line wins) | **truth** for "why and how it was downloaded" (`user_note`, `context`, source, tags) |
| **Catalogue** | ai-server `~/homelab/data/hub-index/catalog.sqlite` (system SSD; Cursor confirms `df` shows the root SSD, not `/models` or a USB drive) | new `hub-index` service on ai-server | **cache** serving search; rebuildable |
| Pi fallback snapshot | Pi `$JOBS_DIR/index-snapshot.jsonl.gz` | pushed by `hub-index` after each nightly rebuild | search while ai-server sleeps (items only, no file rows) |

## Diagram

```
                      Hub (Pi, app.py)                                   ai-server
 ┌───────────────────────────────────────────────┐        ┌───────────────────────────────────────────┐
 │ job finishes ──► download-index.jsonl (journal)│──(1)──►│ hub-index service (:3031, LAN only)       │
 │ PATCH /api/index/{id} user_note ──► journal    │ export │  ├─ ingest journal  (every 30 s + nudge)   │
 │                                                │ ?since │  ├─ scan download_dir after each job  (2)  │
 │ GET /api/index/search ──proxy (3 s)──────────────────────►│  ├─ nightly full scan of every root   (3) │
 │        │ ai-server asleep?                     │        │  └─ catalog.sqlite  (FTS5)  ◄──────────┐   │
 │        └─► fallback: index-snapshot.jsonl.gz ◄──────(4)─┤      items + files + links            │   │
 │            ("Hub downloads only" banner)       │        │                                       │   │
 └───────────────────────────────────────────────┘        │  hub-worker ──nudge POST /ingest──────┘   │
                                                           └───────────┬───────────────────────────────┘
                                                                       │ walk + stat (read-only)
                                     ┌─────────────────────────────────┼──────────────────────────┐
                                     ▼                                 ▼                          ▼
                              TNAS /mnt/tnas/…                Media HDD /mnt/media       Expansion HDD /mnt/external/movies
                              (repo-archive, media_archive,   (+ sidecars)               (torrents/, tv/, movies/)
                               website_backups, …)
```

(1) Journal feed: `GET /api/index/export?since=<cursor>` (spec §A6, built in AP-5a) gives every new or updated record; `hub-index` keeps the cursor. (2) After each finished job the worker POSTs `{job_id, download_dir}` to `hub-index /ingest` so that job's files are searchable within seconds. (3) A nightly step rescans every mounted root incrementally. (4) After the nightly rebuild `hub-index` pushes a compact item-level snapshot to the Pi.

## Catalogue model (SQLite, FTS5)

| Table | Rows | Key fields |
|-------|------|-----------|
| `items` | one per logical thing: a Hub download entry, **or** a top-level folder found on a root that has no Hub record (e.g. `tv/The Office/`, `movies/Heat (1995)/`, a repo folder) | `item_id` (= `entry_id` for Hub entries, `fs:<root_id>:<rel_path>` otherwise), `kind`, `title`, `root_id`, `rel_path`, `size_bytes`, `file_count`, `mtime`, `status` (`present` \| `offline` \| `missing`), plus the journal record JSON for Hub entries |
| `files` | one per file under every root | `root_id`, `rel_path`, `name`, `ext`, `size`, `mtime`, `item_id` (longest folder prefix match) |
| `fts_items` | FTS5 over title, description, topics, hub tags, user note, context, readme/card excerpt, folder names | ranks per §A6 weights (title 3, tags/topics 2, description/note 1.5, excerpt 1) |
| `fts_files` | FTS5 over file name + path segments | |
| `roots` | one per scanned root | `root_id` (from `library.json` drive id or `repo_archive`), `host_path`, `last_full_scan`, `mounted` |
| `meta` | journal cursor, schema version | |

Rules:
- **Offline is not deleted.** When a root is unmounted (TNAS asleep, USB unplugged), its rows stay with `status: offline`; search still finds them and says "on TNAS (asleep)". A row becomes `missing` only after a full scan of a mounted root does not find it, and is purged after 30 days missing.
- **Item grouping:** a file belongs to the Hub item whose `rel_path`/`download_dir` is its longest prefix; files under no Hub item are grouped by the first two path levels under known library folders (`tv/<Show>`, `movies/<Film>`, `github-daily/<day>/<repo>`), else by their parent folder.
- **Read-only on storage.** `hub-index` only `stat`s and lists; it never writes to the drives. It uses the worker's existing stale-mount guards (`_safe_check_path`) so a stale CIFS mount cannot hang it.
- **Skips:** `.partial-*`, `.git` internals inside `repo.git`, `snapshot/.cache`, `@eaDir`, `#recycle`, `node_modules`.

## Update triggers

| When | What runs | Cost |
|------|-----------|------|
| Every 30 s while awake | journal tail (`/api/index/export?since=`) | tiny |
| A job finishes (worker nudge) | journal tail + scan of that job's `download_dir` only | seconds |
| Nightly, new overnight step `index-rebuild` after `queue-drain` and `seedvault-sync`, before ai-server sleeps | incremental full scan of every mounted root (skip a directory whose mtime and child count are unchanged since the last scan, but always re-stat files under folders whose mtime changed), then push the Pi snapshot | minutes; bounded by `timeout_min` |
| On demand | `scripts/rebuild-download-index.py --catalog` (drop and rebuild the cache from journals + sidecars + full scan) | longest; the recovery path |

## API

`hub-index` (ai-server, stdlib `http.server` + `sqlite3`, no new pip packages; bound to the LAN/Tailscale address, worker token required for `/ingest`):

| Method | Path | Behaviour |
|--------|------|-----------|
| `GET` | `/search?q=&kind=&root=&scope=items\|files\|all&limit=50&offset=0` | FTS5 match; every term must match (AND); result rows carry `where` ("TNAS › repo-archive › github-daily/2026-10-12/octocat__Hello-World"), `status`, and for file hits the owning item |
| `GET` | `/item/{item_id}` | item + first 200 files + journal record |
| `POST` | `/ingest` | `{job_id?, download_dir?}`: tail the journal now, scan that folder |
| `POST` | `/rebuild` | full scan (used by the overnight step); returns counts |
| `GET` | `/health` | counts per root, last scan times, schema version |

Pi (`app.py`) keeps the public routes from §A6 and proxies:

- `GET /api/index/search` → `hub-index /search` with a 3 s timeout. If ai-server does not answer, it searches `index-snapshot.jsonl.gz` plus the live Pi journal and returns `"source": "pi-fallback"`; the UI shows "ai-server is asleep: showing Hub downloads only. Wake it to search every file."
- `GET /api/index/{entry_id}`, `/card`, `PATCH` (notes), `/export`, `POST /api/index/entries`, `/sources` stay on the Pi exactly as §A6 (they work from the journal, so notes never depend on ai-server being awake).

## Migration from today

| Step | Packet | Change | Data risk |
|------|--------|--------|-----------|
| 0 | today | Pi journal (all kinds; rich for torrents, GitHub, HF), TNAS repo journal, repo sidecars | none |
| 1 | AP-5a | Pi: `/api/index/export`, `/entries`, `/sources`; `rebuild-download-index.py --from-jobs` back-fills minimal journal lines for historic `done` jobs (dry run first; PM reviews the count) | append-only; nothing rewritten |
| 2 | AP-5a | ai-server: `hub-index` service + `catalog.sqlite`; first run ingests the Pi journal, the TNAS journal, all sidecars, then a full scan | new file on the SSD only |
| 3 | AP-5a | worker nudge after each job; overnight `index-rebuild` step; Pi snapshot push | none |
| 4 | AP-5b | Pi search proxy + fallback; **Index panel** (`?panel=index`), context cards, "Why I kept this" note, queue rows link to their item | none |
| 5 | AP-5c | rich builders for `video`, `website_archive`, legacy `github`/`hf` + `.hub-index-<id>.json` sidecars; `test_every_download_kind_has_builder` | append-only |

The two JSONL journals are never replaced; the catalogue is added beside them. Deleting `catalog.sqlite` loses nothing.

## Packets

**Split (PM, 2026-10-12):** AP-5a ships as **AP-5a.1** (Pi export/entries/sources/search/card/note, delete tombstones, `ABOUT-THIS-DOWNLOAD.md`, `--from-jobs`; tests I1, I10–I13) and **AP-5a.2** (everything on ai-server below; tests I2–I9, I14). The export cursor is the journal byte offset (`X-Index-Cursor`).

**AP-5a Catalogue and indexer (worker side + Pi export).** Files: `hub_index.py` (new: schema, ingest, scan, search, HTTP server), `scripts/systemd/hub-index.service` (user unit on ai-server), `app.py` (`/api/index/export`, `/entries`, `/sources`), `hub-worker.py` (nudge), `scripts/overnight-run.py` + `overnight-schedule.default.json` (`index_rebuild` step type), `scripts/rebuild-download-index.py` (`--from-jobs`, `--catalog`), deploy manifest (`hub_index.py` in `[worker]`), `docs/DOWNLOAD-INDEX.md` (new). Tests below.

**AP-5b Search API and Index panel.** Pi proxy + fallback + snapshot reader, Index panel UI per §A6 "UI", context cards, note editing, queue links.

**AP-5c Remaining kinds.** Rich builders and sidecars for video, website, legacy repo kinds.

## Tests (PM writes)

| id | case |
|----|------|
| I1 | ingest journal fixture → items with §A6 fields; last line wins on duplicate `entry_id` |
| I2 | scan a temp tree with `tv/Show/Season 1/*.mkv`, a repo folder with sidecar, loose files → item grouping as specced; skips honoured |
| I3 | rescan after deleting a file on a mounted root → `missing`; unmounted root → `offline`, rows kept |
| I4 | incremental scan only re-stats changed folders (count stat calls) |
| I5 | FTS: AND semantics, ranking weights, file hits return their owning item |
| I6 | `/ingest` requires the worker token; `/search` never returns secrets (`secret_scan` on output) |
| I7 | Pi proxy: hub-index up → its results; down (connection refused / timeout) → fallback with `source: "pi-fallback"` |
| I8 | snapshot push round-trip: written gzip JSONL → Pi fallback search finds an item by note text |
| I9 | overnight `index_rebuild` step calls `/rebuild` over `ssh_ubuntu` and honours `timeout_min` |
| I10 | `rebuild-download-index.py --from-jobs --dry-run` prints counts and writes nothing |

## Live acceptance (Cursor, `scripts/smoke-ap5a-index.sh`)

1. `hub-index` active; `/health` lists every mounted root with a scan time; catalogue file is on the root SSD.
2. Search "Hello-World" → the GitHub archive item on TNAS; search a known show name → its `tv/` folder and episode files; search a word from a `user_note` → that item.
3. Finish a tiny job (the HF smoke model with `refresh`) → searchable within 60 s without a full scan.
4. Unmount nothing; instead stop `hub-index` → Pi search returns `pi-fallback` with Hub downloads only; start it again.
5. Run the overnight `index-rebuild` step on its own → counts in the run log; Pi snapshot timestamp updated.

## Per-download record, deletes and nightly (Finn, 2026-10-12)

Finn's ask: every download is indexed **for a person and for a machine**, and the index changes when something is deleted and after the nightly sync.

**One record per download, two views.**

| View | Where | Content |
|------|-------|---------|
| Machine | journal line (truth) + catalogue row; for folder downloads also `.hub-provenance-<job>.json` beside the files (exists today for GitHub/HF) | `schema`, `job_id`, `kind`, `segment` (AP-UX-1), `source_id`, url, title, tags, `user_note`, `context`, destination, file list summary (count, bytes, top files), licence, timestamps, `status` (`present` / `offline` / `missing` / `deleted`) |
| Person | Hub Index panel (AP-5b) card for the item, and for folder downloads `ABOUT-THIS-DOWNLOAD.md` beside the files | Title, where it came from, why it was kept (`user_note`), when, size, what is inside, where it lives now |

TV and film torrents get no file beside them: Sonarr/Radarr move the files out of `torrents/`, so a sidecar would be left behind. Their record lives in the journal and catalogue and gains `library_path` once the import is confirmed (audit phase 2, M5).

**Deletes.**

- Deletes made through the Hub (`POST /api/storage/delete`, `POST /api/jobs/{id}/purge-complete`, cancel + purge) append a tombstone to the journal (`{"event": "deleted", "job_id", "paths", "by", "at"}`) and nudge `hub-index /forget`. The catalogue marks the item and its files `deleted` at once. Deleted items drop out of normal search, stay findable with a "deleted" filter for 30 days, then are purged.
- Deletes made outside the Hub (Finder, Sonarr upgrades, manual `rm`) are found by the next scan: `missing` (see "Offline is not deleted").

**Nightly.** The `index-rebuild` overnight step runs after `queue-drain` and `seedvault-sync` (the nightly sync), then pushes the Pi snapshot. The overnight card shows the step with counts (`new`, `changed`, `missing`, `deleted`).

| id | case | expected |
|----|------|----------|
| I11 | `POST /api/storage/delete` on an indexed folder | journal tombstone; catalogue `deleted` within 5 s (nudge); absent from default search, present with `status=deleted` filter |
| I12 | finished folder job (GitHub, website, file) | `ABOUT-THIS-DOWNLOAD.md` and `.hub-provenance-<job>.json` written; the md contains title, source, note and size; no secrets (scrubbed like the readme excerpt) |
| I13 | finished TV torrent | no sidecar in `torrents/`; journal entry with `segment: "tv"` |
| I14 | overnight run with the step | step result carries `{new, changed, missing, deleted}` and the card renders them |

## Out of scope

- Semantic or RAG search (`ai_summary` stays reserved; a later packet can add embeddings behind the same `/search`).
- Content indexing inside files (only names, paths and Hub metadata).
- Indexing the Mac or other machines.
