# Bucket-HUB roadmap and todo list (PM, 2026-10-12)

Ordered by what unblocks Finn soonest. Packet ids are what handoffs, QC files and branches use. "PM" = PM writes code/tests/smoke; "Cursor" = deploy + QC; "Finn" = only Finn can do it.

## Priority and why

1. **OPS-HF1 gateway assets** first: the Glance queue is broken (`escHtml is not defined`), which also hides the AP-4.1 Accept-licence UI. One Caddy route; code is done.
2. **AP-4.1 QC** second: code is deployed and passing; only the live gated smoke and Finn's click remain. Closing it finishes "paste an HF link and it downloads".
3. **MERGE-1** in parallel with 1–2: four stacked PRs make every rebase riskier. Cursor merges (Finn authorised 2026-10-12).
4. **AP-UX-1 presets and segments** (Finn: pressing) before the index: it fixes a daily confusion (drive chips for TNAS-only kinds), removes a real inconsistency (Firefox magnets land in `nas/inbox`, form magnets in the Sonarr inbox), and is mostly Pi + form work. Small to medium.
5. **AP-5a/5b index** (Finn: pressing; per-download record for people and machines, updated on delete and after the nightly sync): biggest new piece (new ai-server service); benefits from presets because jobs then carry consistent destinations. Medium to large.
6. Audit phases 1b (season-first TV ranking) and 2 (confirm Sonarr imports, which also fills `library_path` in the index), then hygiene, AP-5c, AP-6–8.

PM starts AP-UX-1 code now on `pm/ap-ux-1` (from `pm/ap-4.1`, rebased onto `main` when #7 merges), so it is ready for Cursor as soon as AP-4.1 QC passes.

Finn's suggested order (hotfix → AP-4.1 → presets → index) is kept.

## Todo

### Now: unblock the Hub UI and close AP-4.1

| # | Task | Who | Depends on | Status |
|---|------|-----|-----------|--------|
| 1 | OPS-HF1: Caddy route `/assets/hub-escape.js`; `[gateway]` manifest section (Caddyfile + glance.yml → `~/homelab/glance/`); `verify-deploy-parity.sh gateway`; asset-route test | PM | — | ✓ done (`pm/ap-4.1` `4458018`, 241 tests) |
| 2 | OPS-HF1 deploy: copy `[gateway]` files, restart `hub-gateway glance`, parity `gateway`, `:3000/assets/hub-escape.js` = 200, Glance queue loads | Cursor | 1 | open |
| 3 | Confirm the worker's deployed `hub-worker.py` compiles (an uncommitted indentation-damaged copy appeared in the Mac checkout at 16:42 AEST; PM restored it and saved the diff to `.tmp-hub-ui/hub-worker-indent-damage-2026-10-12T0642.patch`) | Cursor | — | open |
| 4 | `HF_TOKEN` in `hub-worker.env` (Cursor presence check). Finn keeps the current token active while testing and revokes/replaces it in a few days | Finn (+ Cursor presence check) | — | open; revoke later |
| 5 | `GATE_REPO`: Finn asked for ~20 GB; PM chose `google/gemma-2-9b` (fallback `google/gemma-2-9b-it`); Cursor checks gated = auto, size ≤ 20 GB, not yet accepted | PM → Cursor | — | chosen |
| 6 | AP-4.1 QC r2: phase 1 smoke → Finn checks the UI and accepts → phase 2 → disk checks → `AP-4.1-r2.json` | Cursor + Finn | 2, 4, 5 | open |

### Merge sequence (MERGE-1)

| # | Task | Who | Depends on |
|---|------|-----|-----------|
| 7 | Merge PR #5 (AP-3.1) into its base (`--merge`) | Cursor (Finn authorised 2026-10-12) | — |
| 8 | Retarget #6 (AP-4) to that base (GitHub drops the AP-3.1 commits from its diff); merge | Cursor | 7 |
| 9 | Retarget #7 (AP-4.1 + OPS-HF1) to that base; merge after OPS-HF1 and AP-4.1 QC pass | Cursor | 6, 8 |
| 10 | New PM branches start from `main` after 9 | PM | 9 |

### AP-UX-1 download presets (spec: `AP-UX-1-download-presets.md`)

| # | Task | Who | Depends on |
|---|------|-----|-----------|
| 11 | Finn reviews the preset table (esp. film torrents → flat `torrents/` inbox, video → `nas/media_archive`) | Finn | spec |
| 12 | `download_presets.py` registry + `resolve_drive(role)`; `GET /api/presets`, `POST /api/presets/resolve`; `POST /api/jobs` `preset`/`manual_path`; capture + Requests through the resolver; tests P1–P12 | PM | 10, 11 |
| 13 | Form: preset chips in Media / Repo archive / Website groups, Saves-to line, Manually set path toggle, remove Type select, toasts name destination | PM | 12 |
| 14 | `smoke-apux1-presets.sh` (R0–R5, no downloads) + handoff | PM | 12, 13 |
| 15 | Deploy + QC `AP-UX-1-r1.json`; Finn checks the Download tab | Cursor + Finn | 14 |

### AP-5 index (spec: `AP-5-index-architecture-v2.md`, revises §A6)

| # | Task | Who | Depends on |
|---|------|-----|-----------|
| 16 | Finn confirms the architecture (ai-server SQLite catalogue as cache; journals + files as truth; Pi fallback while ai-server sleeps) | Finn | spec |
| 17 | AP-5a Pi side: `/api/index/export`, `/entries`, `/sources`; `rebuild-download-index.py --from-jobs` | PM | 10, 16 |
| 18 | AP-5a ai-server side: `hub_index.py` (schema, ingest, scan, FTS5 search, HTTP `:3031`), `hub-index.service`, worker nudge, overnight `index_rebuild` step, snapshot push; tests I1–I10 | PM | 17 — ✓ done (`pm/ap-5a2`, 340 tests) |
| 19 | AP-5a deploy + QC: back-fill dry run (PM reviews count), first full scan, smoke steps 1–5 | Cursor | 18 |
| 20 | AP-5b: Pi search proxy + fallback; Index panel (`?panel=index`), context cards, "Why I kept this" notes, queue rows link to items | PM → Cursor | 19 |
| 21 | AP-5c: rich builders + sidecars for video, website, legacy `github`/`hf`; `test_every_download_kind_has_builder` | PM → Cursor | 20 |

### Hygiene and later

| # | Task | Who | Notes |
|---|------|-----|-------|
| 22 | P2: a torrent job with a stale aria2 gid stays `running` after a worker restart (no longer blocks lanes since AP-3.1 r4) | PM | small; can ride with AP-UX-1 |
| 23 | Glance `?v=` bump rule: any `form.html` change bumps `glance.yml` and deploys `[gateway]` (now enforced by parity `gateway`) | PM/Cursor | process |
| 24 | Legacy "Hugging Face files (to drive)": keep for selected files only (AP-UX-1 `hf_files` preset); revisit removal after AP-5c | PM | |
| 25 | AP-6 recurring runner, AP-7 GitHub stars / HF likes → queue, AP-8 release tracking | PM | after AP-5a (they use `/api/index/sources`) |
| 26 | Local agent over the catalogue: ask a local model (ai-server vLLM) what a download is, its context and why it was kept; semantic search / `ai_summary` | PM → Cursor | Finn asked for this on 2026-10-11 ("talk to a local agent with the file"); after AP-5b. `docs/DOWNLOAD-INDEX.md` already says how an agent reads the catalogue |
| 27 | **AP-9 video polish** (slimmed by Finn 2026-10-12; yoinks repo considered, broad social lane dropped): resolution chips Best/1080p/720p, X links → video, every video job in `METUBE_IMAGE` (ffmpeg). Spec `AP-9-social-video.md` § AP-9.1 | PM → Cursor | small; after AP-5a.2 |

### Separate projects and ideas (Finn, 2026-10-12: "add that as its own item; these will be a different project / idea")

Each of these gets its own spec and packet ids. None is part of AP-5a.2.

| # | Item | Who | Notes |
|---|------|-----|-------|
| 28 | **REPO-SYNC: nightly freshness check of archived repos.** Every night after the queue drain, check each archived GitHub repo for new commits (and each HF repo for a new revision). Pull what changed without deleting anything: refs that upstream force-pushed or deleted are kept under a history ref, and HF keeps the newest few revisions. Record "updated from → to" in the catalogue | PM spec → PM code → Cursor | Finn 2026-10-11 ("checking for new releases … perhaps with SOME historic versions backed up") and 2026-10-12 ("checking the repos we've cloned … new pushes for us to pull"). AP-8 covers **releases** only and lists mirror refresh as out of scope, so this is new. Runs before the nightly `index_rebuild`. Needs AP-6 (runner) or an overnight step |
| 29 | **Social downloader (parked idea).** Instagram, Facebook, Reddit, TikTok, Threads: per-site cookies, platform registry, own segment; `https://github.com/pablostanley/yoinks` as reference | — | Dropped from AP-9 on 2026-10-12 (Finn mainly wants YouTube). Probe results kept in `AP-9-social-video.md` (Instagram needs login, Facebook "Cannot parse data", Reddit 404 via the VPN) |
| 30 | **Looping Jobs tab + daily top-starred repo.** Own Hub tab listing every recurring job (next run, last result, on/off, Run now); first job archives GitHub's top-starred repo of the day to TNAS, non-destructively | PM → Cursor | Finn 2026-10-11. Specs written: `looping-jobs-github-daily.md`, `looping-jobs-ui.md`. AP-6 builds the runner but lists the tab as out of scope, so the tab is its own packet (AP-6b) |
| 31 | **Overnight as a visual workflow (OVN-2).** Critical steps (wake, sync, drain, index, sleep) shown locked; anything queued during the day is added to tonight's plan automatically; no manual ordering | PM → Cursor | Finn 2026-10-11 (screenshot of the nightly queue). AP-2 shipped the run-scoped report only |
| 32 | **Local preview of archived websites.** Open an archived site from the Hub in a throwaway local web server (Docker), read-only; fix the viewer path traversal (audit L5) | PM → Cursor | Audit §4, phase 4 (P3). Finn's audit brief 2026-10-11 |
| 33 | **Final technical QC pass by Claude** in a terminal once the build list is done: tests, parity on all hosts, smokes, log review, a written report | PM (Claude) | Finn 2026-10-11. Needs a shell that reaches the hosts (Cursor runs the commands; PM writes the script and reads the output) |

### Audit leftovers (`bucket-hub-audit-2026-10.md` §7, never ticketed)

| # | Task | Who | Notes |
|---|------|-----|-------|
| 34 | Phase 1b: season-first TV ranking (demote `full_show`; a bare show search re-queries per season; "include complete packs" toggle) | PM → Cursor | P1 |
| 35 | Phase 2: import truth (poll the Sonarr command id, record "imported: n episodes", show "In library: tv/…") | PM → Cursor | P1; also fills `library_path` in the catalogue. Pairs with the Retry library import button (row 38) |
| 36 | Phase 2b: `create_folder` sanitise and dedupe; `validate_aria2_destination` uses `Path.resolve()` | PM | P2 |
| 37 | Phase 3/3b: Jackett `/dl/` fetched without redirects or through Gluetun; strip `apikey` from stored job URLs; show "Waiting for VPN" on requeued archive jobs. (L2 `_is_aria2_job` was fixed by AP-1 `job_kinds.py`) | PM | P2 |

### Ops and hygiene from Cursor reports (in PROJECT-STATE, not yet on this list)

| # | Task | Who | Notes |
|---|------|-----|-------|
| 38 | Retry library import button on a finished torrent; restart Sonarr/Radarr after a Gluetun restart | PM | from OPS-ARR2 |
| 39 | Dedupe repeated queue clicks for the same URL; size warning for large ungated third-party HF repos | PM | Cursor AP-UX-1 notes, 2026-10-12 |
| 40 | Pi ↔ worker heartbeat timeouts under load; aria2 error 13 (partial file without `.aria2`) policy | PM | PROJECT-STATE P2 |
| 41 | Finn: revoke and replace the HF token pasted in chat; re-export MeTube YouTube cookies when they expire | Finn | |
| 42 | PM ↔ Cursor audit trail: Cursor posts each QC JSON's summary as a comment on the packet's PR, so GitHub holds the trail and Finn pastes less | Cursor | Finn 2026-10-11. QC JSON files in the repo already cover most of it; starts with the next prompt |

## Decisions Finn can change

- Film torrents use the flat `torrents/` inbox (Radarr imports), like TV. Finn agreed (2026-10-12) on condition that existing connections keep working: AP-UX-1 changes no Sonarr/Radarr/aria2/Jellyfin config, and R0 checks the current paths read-only first.
- Catalogue lives on ai-server's system SSD; search falls back to "Hub downloads only" while ai-server sleeps.
- Repo archives live on TNAS (`/mnt/tnas/repo-archive`). The 2026-10-11 idea of repurposing the unused 5 TB drive for GitHub/HF is parked; say if you want it as overflow.
- OPS-HF1 rides on `pm/ap-4.1` / PR #7 (that branch is what is deployed), not a separate PR.
