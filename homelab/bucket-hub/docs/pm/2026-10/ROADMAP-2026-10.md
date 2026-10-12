# Bucket-HUB roadmap and todo list (PM, 2026-10-12)

Ordered by what unblocks Finn soonest. Packet ids are what handoffs, QC files and branches use. "PM" = PM writes code/tests/smoke; "Cursor" = deploy + QC; "Finn" = only Finn can do it.

## Priority and why

1. **OPS-HF1 gateway assets** first: the Glance queue is broken (`escHtml is not defined`), which also hides the AP-4.1 Accept-licence UI. One Caddy route; code is done.
2. **AP-4.1 QC** second: code is deployed and passing; only the live gated smoke and Finn's click remain. Closing it finishes "paste an HF link and it downloads".
3. **MERGE-1** in parallel with 1–2: four stacked PRs make every rebase riskier. Cursor merges (Finn authorised 2026-10-12).
4. **AP-UX-1 presets** before the index: it fixes a daily confusion (drive chips for TNAS-only kinds), removes a real inconsistency (Firefox magnets land in `nas/inbox`, form magnets in the Sonarr inbox), and is mostly Pi + form work. Small to medium.
5. **AP-5a/5b index**: biggest new piece (new ai-server service); benefits from presets because jobs then carry consistent destinations. Medium to large.
6. Hygiene and AP-5c, AP-6–8 after.

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
| 18 | AP-5a ai-server side: `hub_index.py` (schema, ingest, scan, FTS5 search, HTTP `:3031`), `hub-index.service`, worker nudge, overnight `index_rebuild` step, snapshot push; tests I1–I10 | PM | 17 |
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
| 26 | Later: semantic search / RAG over the catalogue (`ai_summary`) | — | only if Finn promotes it |

## Decisions Finn can change

- Film torrents use the flat `torrents/` inbox (Radarr imports), like TV. Finn agreed (2026-10-12) on condition that existing connections keep working: AP-UX-1 changes no Sonarr/Radarr/aria2/Jellyfin config, and R0 checks the current paths read-only first.
- Catalogue lives on ai-server's system SSD; search falls back to "Hub downloads only" while ai-server sleeps.
- OPS-HF1 rides on `pm/ap-4.1` / PR #7 (that branch is what is deployed), not a separate PR.
