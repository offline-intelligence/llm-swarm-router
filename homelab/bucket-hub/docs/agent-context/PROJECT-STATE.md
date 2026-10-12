# PROJECT-STATE — living context (Homelab integration)

**Maintainers:** Claude PM proposes `## CONTEXT UPDATE`; **Cursor implementer** merges into this file when you paste (see `.cursor/rules/homelab-pm-context.mdc`).  
**Last updated:** 2026-10-12 (AP-UX-1 r2 + AP-4.2 r1 QC pass; `handoffs/PM-PASTE-2026-10-12-browser-qc.md`)

Claude Project: read this file **every session**. Emit patches in `## CONTEXT UPDATE` at end of replies.

---

## Current decisions

- **TV folder model:** Hub stops creating `torrents/<Show>/Season NN`. `torrents/` is the aria2 inbox (`torrents/<release folder>/`); `tv/<Show>/Season N` is the Sonarr-owned library. (Audit 2026-10, C1/C2.)
- **Deploy parity is mandatory:** every packet's deploy runs `scripts/verify-deploy-parity.sh` for Pi and worker, driven by `scripts/deploy-manifest.txt`.
- **Job-kind routing:** a job is aria2 only when `worker == "aria2"`, or no worker and `kind` in {http, magnet}. Shared rule in `job_kinds.py`.
- **Repo archive is segmented from media:** GitHub and HuggingFace downloads get their own job kinds, claim lane and destination roots (spec: `cursor-github-hf-downloader.md`, after AP-1 and AP-2).
- **Testing evidence:** each packet ships `docs/testing/AP-n-test-report.md`.
- **Download index is the top priority:** shared `index_writer.py` (schema v1); every finished job of every kind appends to `$JOBS_DIR/download-index.jsonl` (rich entry for torrents from AP-1, minimal fallback for other kinds until AP-5).
- **Review loop:** Cursor opens a draft PR per packet (`cursor/ap-N`) and posts a "Handoff to PM" comment (also saved to `docs/pm/2026-10/handoffs/AP-N.md`); the PM replies go or no-go before the next packet.
- **Merge order (2026-10-12):** AP-1 → AP-2 → AP-3 (rebased onto `hub/audit-handoff-2026-10`). #1 and #2 merged; `cursor/ap-3` rebased to `71b7323`.
- **PR #3 merges now (2026-10-12, supersedes "fast-follow before merge"):** AP-3 bytes are already live on Pi and worker, so holding the PR only leaves git behind production. The §T6 gaps are ops (connectivity, TNAS, image, env), not code. Fast-follow ships as **AP-3.1**, a separate PR on top.
- **§T6 is a deploy gate, not a merge gate:** a packet's PR may merge with §T6 incomplete when the cause is environment-only and the code is already deployed; the packet is not *done* until §T6 passes.
- **AP-4 implementer (2026-10-12):** PM Claude writes AP-3.1 and AP-4 in the folder thread; Cursor deploys and runs SSH smokes only.
- **Go with partial coverage (2026-10-12):** a packet may get GO with deferred tests when those tests are integration-shaped and do not cover the packet's core bug fix (e.g. AP-3 §T2).
- **Role shift (2026-10-12):** PM Claude writes code directly in this repo via a folder thread; Cursor's role is deployment and SSH smoke tests only.
- **AP-3 status (2026-10-12, after TNAS restore):** live for manual, one-at-a-time public `github_repo` jobs. **Not done:** §T6 step 2 (repo + torrent in parallel) was not run, and step 3 fails the spec because `README.md` is missing. Until AP-3.1 deploys, do not leave `github_repo` jobs queued while torrents are queued.
- **README.md beside `repo.git` is required, not a spec gap (2026-10-12):** spec A3 layout, A5 step 7 and §T6 step 3 all require it. Cause: `docker/repo-archiver/repo_archiver_entry.py` only tries `git show HEAD:README.md`; `octocat/Hello-World` has `README` (no extension), so nothing is written and `readme_excerpt` is empty. Fix in AP-3.1: resolve the README case-insensitively from `git ls-tree HEAD` (`README`, `README.md`, `.rst`, `.txt`, `.markdown`), always write it as `README.md`; then re-queue Hello-World with `options.refresh: true`.
- **AP-3.1 before AP-4 (2026-10-12):** the lane-blind claim is a live production bug now that the repo lane works: while a repo job occupies `HUB_SLOT_REPO`, any queued repo job sorted ahead of torrents is claimed by the aria2 loop, re-queued, and the loop `break`s, so torrents stall for the whole clone (up to 4 h). AP-4 adds more long repo jobs and would make it worse. AP-4 starts after AP-3.1 passes §T6 step 2.
- **`HUB_GITHUB_TOKEN` (2026-10-12):** set on ai-server `hub-worker.env` (fine-grained, public read); worker restarted. Still optional for single public clones; needed before AP-6/AP-7 volume for metadata rate limits.
- **TNAS LAN IP (2026-10-12):** NAS at `192.168.50.187` (LAN 2 MAC `6c:bf:b5:04:69:67`). ASUS RT-AX57 **DHCP manual assignment** `tnas` → `.187` applied; Hub/Kuma/mount verified. TNAS may stay on DHCP or manual static — both aligned with reservation.
- **PM ↔ Cursor loop (2026-10-12, Finn):** PM writes code, tests and smoke scripts on `pm/<packet>`; Cursor only integrates, deploys, tests and returns a QC report JSON (`bucket-hub-qc/v1`, `docs/pm/<yyyy-mm>/qc/<packet>-r<n>.json`); PM fixes findings in the next round. Cursor never edits app code to make checks pass. Spec: `docs/pm/PM-CURSOR-PROTOCOL.md`; Cursor rule `.cursor/rules/homelab-pm-context.mdc`.
- **UI sign-off (2026-10-12):** integrator browser QC that Finn forwards to the PM counts as Finn's sign-off for ui.* checks; PM states acceptance in the next handoff.
- **Sonarr/Radarr transport (2026-10-12, OPS-ARR2):** the host worker calls Sonarr/Radarr with docker exec (`SONARR_VIA_DOCKER=sonarr`, `RADARR_VIA_DOCKER=radarr`); host loopback and LAN publish into Gluetun return 000 while the apps answer inside (BindAddress *, namespace current). Doctor: `arr_client.py --check`.
- **Download index shape (2026-10-12, AP-5a.1):** the Pi journal stays append-only truth; deletes are `{"event":"deleted"}` tombstones and notes `{"event":"note"}` lines, merged on read (`download_record.load_records`); machines read `GET /api/index/export?since=<byte cursor>`. TV/film torrents get no sidecar (Sonarr/Radarr move files).
- **Merge rule (2026-10-12):** Cursor merges a PR only after its QC overall = pass and the PM handoff names the merge.
- **AP-3.1 shape (2026-10-12):** lane-aware claim is opt-in per request (`{"lane": …}`), so Pi deploys before worker and an old worker keeps working. TNAS defer back-off uses a job-level `not_before` honoured by every claim, not worker-side sleeps.
- **Worker restart recovery (2026-10-12, AP-3.1 r2):** at startup the worker re-queues every repo/repo_meta job the Pi shows as `running`/`claimed` (no repo thread survives a restart) and removes its archiver container `hub-repo-partial-<id>`; repo claims wait until this has run. Single-worker assumption: a second worker would need ownership tracking first.
- **Repo archive content (2026-10-12, AP-3.1 r3):** `repo.git` is a bare repo with branches and tags only (`+refs/heads/*`, `+refs/tags/*`), `HEAD` = remote default branch. No `refs/pull/*`: `clone --mirror` pulled every PR head (fork commits the API `size` ignores) and blew the cap on `octocat/Spoon-Knife`. Image `bucket-hub-repo-archiver:3`.
- **TNAS defer (2026-10-12, AP-3.1 r3):** a repo job is deferred only after a second mount check `HUB_REPO_RECHECK_S` (5 s) later; a stale mark clears once the mount answers `stat`. The defer note names the reason.
- **Smoke torrent (2026-10-12):** `smoke-ap31-lanes.sh` uses the Sintel magnet (proven well-seeded in r1). A torrent that is claimed on time but gets 0 bytes points at the swarm, not the lane fix; swap back to Sintel rather than changing code.
- **Worker loop isolation (2026-10-12, AP-3.1 r4):** aria2 housekeeping errors are logged and contained, never allowed to skip the video or repo claims in the same tick. aria2 JSON-RPC errors (HTTP 400) surface as `RuntimeError`, so `hub http 4xx` in the worker log now means the Hub only.
- **Smoke validity rule:** a smoke run with a worker restart or env edit during it is invalid; re-run from scratch.
- **AP-3 is done when `scripts/smoke-ap31-lanes.sh` passes** (adversarial §T6 step 2 plus Hello-World `README.md`). AP-4 starts after that.
- **Archive-root kinds (2026-10-12, AP-4):** `job_kinds.ARCHIVE_ROOT_KINDS` = `github_repo`, `huggingface_repo`, `github_release`. They write under the TNAS repo-archive root, never a library drive, so `POST /api/jobs` skips the drive check for them (and for repo-meta kinds) only. Legacy `hf` / `github` drive jobs get a `destination_path` again (the old early branch dropped it).
- **Hugging Face layout (2026-10-12, AP-4):** `huggingface-daily/<YYYY-MM-DD>/<models|datasets>__<org>__<name>/` holds `snapshot/`, `README.md` (the model card) and the sidecars; snapshot pinned to the metadata `sha`. Spaces are rejected. Options: `prefer_safetensors` (default on: drops `.bin/.pt/.pth/.ckpt/.h5/.msgpack` when safetensors exist), `allow_patterns` (wins, always adds `README.md`), `ignore_patterns`, `max_size_mb` (pre-check from metadata, post-check at 110 %), `revision`, `refresh`. Errors read `Repository not found or private` or the gated message.
- **Archiver image `:4` (2026-10-12, AP-4):** adds `hf_snapshot` (`huggingface_hub==0.26.2`); GitHub path unchanged from `:3`. Worker env `REPO_ARCHIVER_IMAGE=bucket-hub-repo-archiver:4`. `HF_TOKEN` in `hub-worker.env` is optional, only for gated models; it reaches the container through env, never argv.
- **Index free text is scrubbed (2026-10-12, AP-4):** `index_writer.scrub_free_text()` redacts `ghp_` / `github_pat_` / `hf_` tokens, `Bearer` values and `token=` query strings from readme excerpts and model cards (GitHub and HF).
- **Form kinds (2026-10-12, AP-4):** the Hub form offers "GitHub repo (TNAS archive)", "Hugging Face repo (TNAS archive)" and "Hugging Face files (to drive)" (legacy `hf`); search results queue the archive kinds; a files-mode HF pick with selected files stays `hf`.
- **HF gated models (2026-10-12, Finn):** pasting an HF link is the main use case and must not dead-end at a gated licence. AP-4.1 (`docs/pm/2026-10/AP-4.1-hf-gated-access.md`): gated jobs wait as `queued` with `gate.state = awaiting_licence` and re-check every 10 min for 7 days; the Hub shows Accept licence / Check now, so one click finishes the job. `huggingface_hub` has no user-side accept API (owner-side only), so Finn chose **one click** (2026-10-12): no auto-accept, no HF session cookie stored. Gated downloads always need `HF_TOKEN` from the same HF account.
- **Gated HF jobs are not errors (2026-10-12, AP-4.1):** a gated repo without access is `queued` + `gate` + `not_before`; the worker re-probes with one `HEAD` on the AP-4.2 schedule (gaps 1, 5, 30 min, then hourly; `HF_GATE_SCHEDULE_S`), shows `gate.state = granted` while downloading; it errors only after `HF_GATE_MAX_WAIT_H`. The Pi never calls huggingface.co (all HF traffic via the worker's Gluetun), so there is no paste-time licence check; the job shows the state within one claim.
- **Pi restart command unknown (2026-10-12):** `sudo systemctl restart hub-form` reported "unit not found" in AP-4 r1. r1b finds the real unit/container and fixes `05-OPERATIONS-SSH-DEPLOY.md`. Until then a Pi deploy may leave old `app.py` running even when parity passes.
- **Cursor prompt shape (2026-10-12):** every Cursor prompt includes an explicit **READ FIRST** file list and a **DOCUMENTS TO UPDATE** list (CHANGELOG.md, PROJECT-STATE.md, deps file, API docs, module docstrings, packet handoff).

| Topic | Decision |
|-------|----------|
| TV torrents | **Season-by-season** preferred; **discourage** full-series complete packs (size, aria2, Sonarr). Flat `torrents/` inbox. |
| Breaking Bad S01 | Shipped via **season pack** + manual Sonarr scan; Jellyfin **TV Shows (Sonarr)**. |
| Training Day / metadata | Magnet-only dead swarms → use Jackett **`.torrent` URL**; metadata stall = `metadata_stuck` in `job_health.py`. |
| Resume vs Retry | After aria2 restart, **Retry** (clears dead `aria2_gid`); Resume keeps stale gid. |
| Implementer | PM Claude writes code via folder thread (from 2026-10-12); Cursor integrates, deploys, tests and returns QC JSON (`PM-CURSOR-PROTOCOL.md`). Deploy Pi `~/homelab/hub-form/`, ai-server `~/homelab/scripts/hub-worker.py`. |
| Claude PM | ~~Specs and Action Packets only~~ (superseded 2026-10-12: also writes code); no secrets in docs. |
| Job UI cleanup | **Dismiss** `error`/`done` jobs; `dismiss-queue` clears failed strip; cancel+purge removes disk, not JSON until dismiss. |
| TNAS power | WoL from Pi **best-effort**; hard-off NAS needs physical power or TOS WoL enabled. |
| Website archive | “Website copy” = clone-to-disk system ([09-WEBSITE-ARCHIVE-SYSTEM.md](09-WEBSITE-ARCHIVE-SYSTEM.md)); local Docker preview **not built**. |
| Gateway deploy | `Caddyfile` + `glance.yml` live in `~/homelab/glance/` on the Pi (not `hub-form/`); shipped via the `[gateway]` manifest section, checked by `verify-deploy-parity.sh gateway`. Every `/assets/` file a page uses needs a Caddy route (test enforces it). (2026-10-12) |
| Pi restart | `ssh stackrise-pi 'systemctl --user restart hub-form.service'` (user unit). (2026-10-12) |
| Download destinations | One server-side preset registry (`download_presets.py`, AP-UX-1) decides type → place for form, capture, Requests and API; drive/folder only behind "Manually set path". Film torrents default to the flat `torrents/` inbox like TV (Radarr imports). Finn agreed 2026-10-12 provided existing connections keep working: no *arr/aria2/Jellyfin config changes, R0 read-only before/after check. |
| Index architecture | Truth = files + sidecars + JSONL journals; ai-server SQLite FTS5 catalogue (`~/homelab/data/hub-index/catalog.sqlite`, `hub-index` `:3031`) is a rebuildable cache; Pi proxies search and falls back to a snapshot while ai-server sleeps. Spec `docs/pm/2026-10/AP-5-index-architecture-v2.md` (revises §A6). (Finn agreed 2026-10-12) |
| Glance cache-buster | `glance.yml` `?v=` values are cache-busters: a live-only `?v=` difference may be overwritten on gateway deploy; any other gateway drift stops the deploy. Bump `v=` whenever `form.html` changes. (2026-10-12) |
| Gated test model | AP-4.1 accepts manually gated repos (Hub re-checks for 168 h); `google/gemma-2-9b-it` used for QC. (2026-10-12) |
| Priority (2026-10-12) | OPS-HF1 → AP-4.1 QC → MERGE-1 (parallel) → AP-UX-1 → AP-5a/b → hygiene. `docs/pm/2026-10/ROADMAP-2026-10.md`. |
| Off-LAN Hub review (2026-10-12, Finn) | Use Tailscale `http://100.85.42.0:3000/` (and `/hub-form/`); not LAN `.138`. Direct uvicorn: `http://100.85.42.0:3020/hub-form/` only with **trailing slash**. See `01-ARCHITECTURE-AND-NETWORK.md` § Remote review. |

---

## Audit handoff (2026-10-12)

- **Master brief:** [AUDIT-BRIEF-2026.md](AUDIT-BRIEF-2026.md) — live probe snapshot, technology rationale, Claude first message.
- **Deep dives:** `08`–`14` in this folder; index in [00-README.md](00-README.md).
- **pytest (compile):** 54 passed, 2 failed — see [12-FAILURES-LIMITATIONS-TESTS.md](12-FAILURES-LIMITATIONS-TESTS.md).
- **Pi deploy parity:** 2026-10-12 manifest rsync — **22/22** Pi files + **worker parity ok** (`verify-deploy-parity.sh worker`). Use `bucket@100.85.42.0` until `stackrise-pi` SSH HostName fixed.
- **Awaiting Claude auditor:** findings + first Action Packet. Extra required topics: **overnight UI** (`overnight.html`) and **TV folder auto-creation** (`ensureTorrentShowFolder`).
- ~~**Claude is not self-sufficient:** no MCP writes the Mac repo.~~ Superseded 2026-10-12: PM Claude now edits the repo via folder thread. See [15-CLAUDE-AUDITOR-WORKFLOW.md](15-CLAUDE-AUDITOR-WORKFLOW.md). Cursor still merges CONTEXT UPDATE and SSH-deploys via [SSH-PASTE.txt](SSH-PASTE.txt).
- **Recommended auditor model:** Sonnet 4.6 (not Opus for the full read).

---

## Where things are tracked (master documents)

| Question | Document |
|----------|----------|
| What is decided, what is next, what happened (this file) | `docs/agent-context/PROJECT-STATE.md`: decisions, backlog, learnings, session log |
| Goals, priority order and the full todo list | `docs/pm/2026-10/ROADMAP-2026-10.md` |
| What the audit found and the remediation phases | `docs/pm/2026-10/bucket-hub-audit-2026-10.md` (§7 phases) |
| How PM and Cursor work, QC schema | `docs/pm/PM-CURSOR-PROTOCOL.md` |
| Outcome of every round (machine-readable) | `docs/pm/2026-10/qc/<packet>-r<n>.json` |
| What each packet must do | specs in `docs/pm/2026-10/` (AP-4.1, AP-UX-1, AP-5 v2, …) and handoffs in `docs/pm/2026-10/handoffs/` |
| What shipped | repo-root `CHANGELOG.md`; `homelab/bucket-hub/TODO.md` for the short list |

## Learnings (keep; newest first)

- **Test against the config files that actually ship, and pin paths in smokes.** AP-UX-1 unit tests used a hand-made override file, so the shipped `capture-folders.json` (`magnet` → `nas/inbox`) silently moved TV off `torrents/`; smoke R1 only checked "available". Now a test loads the real file and R1 asserts tv/film paths (AP-UX-1 r1 F2).
- **Verify external facts before writing them into a prompt.** PM picked Gemma as an "auto-gated, ~18 GB" test model without checking; it was manually gated and the base model 37 GB (AP-4.1 r2). Cursor's B3 check caught it. PM cannot reach huggingface.co from its tools, so such picks are labelled unverified and Cursor checks first.
- **Every file a host reads must be in the deploy manifest.** The gateway `Caddyfile`/`glance.yml` live in `~/homelab/glance/`, outside the manifest, so a missing `/assets/hub-escape.js` route broke the Glance queue unseen (OPS-HF1). Now `[gateway]` + parity + an asset-route test.
- **Diff live config before overwriting it, and say which differences are safe.** OPS-HF1 r1 stopped correctly on a cache-buster difference; the rule now names `?v=` values as safe.
- **Restarts mid-smoke create false failures.** A worker restart orphaned a running repo job and held the slot (AP-3.1 r1). Smokes now forbid restarts/env edits, and the worker recovers orphans.
- **External APIs report errors in unexpected ways.** aria2 returns JSON-RPC errors as HTTP 400; the uncaught `HTTPError` killed every worker tick (AP-3.1 r3b). Housekeeping is isolated in `main()`.
- **Defaults of upstream tools matter.** `git clone --mirror` fetched GitHub `refs/pull/*` and blew the size cap (AP-3.1 r2); the archiver fetches heads + tags only.
- **The Mac checkout is shared.** An uncommitted, damaged `hub-worker.py` appeared there (2026-10-12). Parity checks proved the deployed copy clean; never deploy from uncommitted files.
- **PM inferences must be marked and tested.** "Legacy hf downloads are LFS pointers" was wrong (AP-4 r1); QC disk checks are the arbiter.
- **Small packets with machine-readable QC work.** Every round since AP-1 ends in a `bucket-hub-qc/v1` JSON; failures were traceable to one cause per round.

---

## Backlog (ordered)

- [x] AP-1 (P0) TV flat inbox + deploy parity + XSS sweep (H1) + `_is_aria2_job` fix (L2) + `index_writer.py` on torrent completion. Accepted (110 tests); **deployed** 2026-10-12 (manual smokes remain).
- [x] AP-1 (#1) — merged into `hub/audit-handoff-2026-10` (2026-10-12).
- [x] AP-2 (#2) — merged into `hub/audit-handoff-2026-10` (2026-10-12).
- [x] AP-3 (#3) — **merged**, deployed. §T6 steps 2–3 **pass** via AP-3.1 QC r4 (`docs/pm/2026-10/qc/AP-3.1-r4.json`). Earlier evidence: job `694e010971e2`, `docs/testing/AP-3-test-report.md`.
- [x] AP-3.1 fast-follow — PR #5 **ready for review**, `pm/ap-3.1`. QC r4 **pass** (2026-10-12): aria2 housekeeping fix deployed; `smoke-ap31-lanes.sh` 6/6. Sub-items:
  - [x] **Lane-blind claim starves torrents:** `hub-worker.py` main loop calls `claim_next()` with no lane, so a queued `github_repo` sorted ahead of torrents is claimed by the aria2 loop, re-queued and `break`s. With TNAS offline the repo job bounces back to `queued` every cycle (no backoff), so torrents queued after it are never claimed. Fix: `POST /api/jobs/claim {"lane": …}` filtered by `_job_kind_bucket`, plus a retry backoff on TNAS defer.
  - [x] `error_display` sent by `repo_archive_github.py` is silently dropped (not in Pi `JobUpdate`), so "TNAS offline, will retry" never shows in the UI; tests only check the fake `update_job`.
  - [x] Deferred §T2 tests: mirror argv and `--network container:gluetun`.
  - [x] `gluetun_http_json` puts `Authorization: Bearer <HUB_GITHUB_TOKEN>` in `docker run` argv (visible in `ps`); pass via env/file instead.
  - [x] Add `docker/repo-archiver/` to the deploy path (manifest or deploy script) so the image can be built on ai-server.
  - [x] **README.md not written** for repos whose README is not exactly `README.md` (see decision). Rebuild image as `bucket-hub-repo-archiver:2`; test with a fake `ls-tree` listing `README` and `readme.rst`.
  - [x] §T6 step 2 acceptance: `scripts/smoke-ap31-lanes.sh` — **pass** QC r4.
- [ ] §T6 ops blockers (Finn; checklist in PM reply 2026-10-12):
  - [ ] Worker → Pi heartbeat/claim timeouts (cause unconfirmed; see P2).
  - [x] TNAS mounted at `/mnt/tnas` on ai-server (`//192.168.50.187/public`), `repo-archive/` root created (2026-10-12).
  - [x] `bucket-hub-repo-archiver:1` built on ai-server.
  - [x] `hub-worker.env`: `HUB_REPO_ARCHIVE_ROOT`, `HUB_SLOT_REPO=1`, `REPO_ARCHIVER_IMAGE`.
  - [x] `hub-worker.env`: `HUB_GITHUB_TOKEN` (fine-grained, public read); worker active (2026-10-12).
  - [x] Router DHCP reservation for TNAS MAC `6c:bf:b5:04:69:67` → `192.168.50.187` (ASUS RT-AX57; 2026-10-12).
  - [x] Replace `192.168.50.186` with `.187` in tracked repo files + Pi deploy (`machines_ctl.py`, `glance.yml`, smoke scripts); runtime `~/homelab/data/hub-jobs/machines.json` on Pi edited in place (2026-10-12). Uptime Kuma TNAS monitor → `http://192.168.50.187:8181/` (API edit on Pi, 2026-10-12).
  - [x] Mac `~/.ssh/config`: `Host stackrise-pi` → `100.85.42.0` (2026-10-12); `verify-deploy-parity.sh pi` **exit 0** after deploy.
  - [x] Re-run §T6 step **2** after AP-3.1 — **pass** QC r4 (2026-10-12).
- [x] AP-4 `huggingface_repo` — QC r1b **pass** (`docs/pm/2026-10/qc/AP-4-r1b.json`): smoke 7/7, real weights on TNAS. PR #6 draft (base `pm/ap-3.1` until #5 merges).
- [ ] AP-4.1 HF gated repos (one click) — **code done** on `pm/ap-4.1` (239 tests). QC r1 blocked (`HF_TOKEN`); r2 issued; `GATE_REPO` = `google/gemma-2-9b-it` (18.5 GB, gated manual; PM choice per Finn); needs Finn's Accept-licence click. Spec `docs/pm/2026-10/AP-4.1-hf-gated-access.md`.
- [ ] OPS-HF1 (P0) gateway route `/assets/hub-escape.js` (Glance queue `escHtml is not defined`) — **code done** `4458018` (241 tests); Cursor deploy + QC `OPS-HF1-r1.json`.
- [x] MERGE-1: **Cursor** merged #5 → `main` (`872dcb4`), retargeted/merged #6 (`0663c39`); #7 retargeted to `main`, merge deferred until OPS-HF1 + AP-4.1 QC pass (2026-10-12 r2).
- [ ] Security: HF token pasted in chat is still active (Finn's choice, for testing); Finn revokes/replaces it in a few days.
- [x] AP-UX-1 download presets + segments (TV & film · Repo archive · Websites · Other) + "Manually set path" — QC r2 **pass** `docs/pm/2026-10/qc/AP-UX-1-r2.json` (2026-10-12). Spec `docs/pm/2026-10/AP-UX-1-download-presets.md`.
- [x] AP-4.2 HF access re-check schedule (1/5/30 min then hourly; Licence needed vs Approval needed copy; `granted` state) — QC r1 **pass** `docs/pm/2026-10/qc/AP-4.2-r1.json` (2026-10-12). Spec `docs/pm/2026-10/AP-4.2-gate-schedule.md`.
- [x] OPS-ARR1 folded into OPS-ARR2 (same fault: worker host cannot reach Sonarr/Radarr).
- [x] **OPS-ARR2** worker → Sonarr/Radarr via `arr_client` + docker exec transport — QC r2 **pass** `docs/pm/2026-10/qc/OPS-ARR2-r2.json`; PR **#12 merged** (2026-10-12).
- [ ] **AP-9 social video** (YouTube, X, Instagram, Threads, TikTok, Facebook, Reddit; yoinks approach in Hub video lane). AP-9.0 probe `handoffs/AP-9.0.md`; spec `docs/pm/2026-10/AP-9-social-video.md`.
- [ ] Backlog: dedupe repeated queue clicks for the same URL; size warning for large ungated third-party HF repos (Finn, 2026-10-12).
- [x] AP-5a.1 per-download record — QC r4 **pass** `docs/pm/2026-10/qc/AP-5a1-r4.json`; PR **#11 merged** (2026-10-12). Operator doc `docs/DOWNLOAD-INDEX.md`.
- [ ] AP-5a.2 ai-server catalogue (`hub_index.py`, SQLite FTS5 on the system SSD, scans every root, outside-Hub deletes → `missing`, worker nudge, overnight `index_rebuild` after the nightly sync, Pi snapshot) — PM builds after AP-5a.1 QC.
- [ ] AP-5b Index panel + search proxy/fallback; AP-5c website/video builders and sidecars — Finn: pressing; spec `docs/pm/2026-10/AP-5-index-architecture-v2.md`.
- [ ] Repo archive later: AP-5 index across all kinds + search, AP-6 recurring runner, AP-7 GitHub stars / HF likes to queue, AP-8 release tracking.

### P0 — TV season-first UX

- [ ] Show-only TV search → Sonarr lookup → **clickable season pips** → Jackett query `{Show} season N}` only.
- [ ] **Hide or demote** `release_kind: full_show` on TV chip (optional “Advanced” override).
- [ ] One season = one queue job; Expansion HDD `torrents/<release>/` (not Show/Season folders).
- [ ] Verify `SONARR_URL=http://127.0.0.1:8989` in `hub-worker.env` (Gluetun network).

### P1 — Automation

- [ ] Daily GitHub top repos: `scripts/github-daily-discover.py` + `github-daily-enqueue.py` (see `07-DAILY-GITHUB-TOP-REPOS.md`).
- [ ] Pi systemd timer (Brisbane); `GITHUB_TOKEN` in worker env (human).

### P2 — Reliability

- [ ] Stale aria2 gid: a Hub job left `running` with a gid aria2 no longer knows (r1 `18d0343be5f5`, r3b `8d817da9a03b`). Since AP-3.1 r4 it no longer blocks other lanes (`aria2()` raises `RuntimeError`, housekeeping isolated), but the job itself still sits `running`. Worker should mark it for Retry (drop the gid, re-add) instead of re-checking it every tick.

- [x] Deploy `job_health.py` to Pi with `app.py` (2026-10-12); verify `agent_review` UI end-to-end.
- [ ] aria2 error 13 (partial without `.aria2`): worker policy or user doc for Retry after cleanup.
- [ ] Reduce Pi ↔ worker heartbeat timeouts under load. Now blocking §T6. Code facts: worker `hub_call` tries `HUB_URL` entries in order (default LAN `192.168.50.138:3020` then Tailscale `100.85.42.0:3020`), 30 s timeout each, and only logs `heartbeat failed` when all fail; Pi `/api/worker/heartbeat` synchronously re-reads every job JSON (`_scan_running_jobs_health`) and merges the library on each 12 s beat. Need the worker log line and job count to confirm which.

### P3 — Later

- [ ] “Missing seasons” batch enqueue (Sonarr episode counts vs queue history).
- [ ] TVMaze fallback if Sonarr lookup fails.

---

## Shipped in repo (not necessarily deployed)

- `docs/agent-context/*` pack
- `job_health.py`, tests, `GET /api/jobs/agent-review`, UI hints (verify deploy)
- `hub_torrent_parse.py` season query filters (deployed earlier for BB S01 search)

---

## Known pain (ops)

- **Office** large complete pack: failed / 0 seeders — prefer per-season.
- **HTTP 400** on worker `PATCH` jobs: Pi API / token / payload; check hub-worker log.
- **TNAS offline**: NAS destinations fail; Expansion HDD is primary for torrents/TV. 2026-10-12 outage was an unplugged cable plus DHCP moving the NAS to `.187`.
- **NAS offline** in Hub UI does not block `ext_movies` torrents.
- **Smoke job `c8a5b6f8b306`** (`github_repo`, Hello-World) is `queued`. Until TNAS is mounted and AP-3.1 lands, dismiss it so it cannot starve torrents queued behind it once the worker reaches the Pi again.

---

## Session log (newest first)

| Date | Note |
|------|------|
| 2026-10-12 | **AP-9.0 QC r2** (`docs/pm/2026-10/qc/AP-9.0-r2.json`): **pass** — Gluetun metadata probe (YouTube+cookies, X ok; IG/FB/Reddit fail classes recorded). Finn: skip Threads/TikTok. |
| 2026-10-12 | **AP-9.0 QC r1** (`docs/pm/2026-10/qc/AP-9.0-r1.json`): **blocked** — probe not run; need Finn public URLs per platform (S0). |
| 2026-10-12 | **OPS-ARR2 QC r2** (`docs/pm/2026-10/qc/OPS-ARR2-r2.json`): **pass** — rebase on main; root cause Gluetun publish; live parity ok; **PR #12 merged**. |
| 2026-10-12 | **AP-5a.1 QC r4** (`docs/pm/2026-10/qc/AP-5a1-r4.json`): **pass** — F1 boundary proved (r3 overlap); smoke 7/7; **PR #11 merged**. |
| 2026-10-12 | Finn added **AP-9 social video** (yoinks approach in Hub yt-dlp lane). Spec `docs/pm/2026-10/AP-9-social-video.md`; probe `handoffs/AP-9.0.md` on `pm/ap9-spec`. |
| 2026-10-12 | **OPS-ARR2 QC r1** (`docs/pm/2026-10/qc/OPS-ARR2-r1.json`): **pass** — docker transport; PR #12 ready (not merged). |
| 2026-10-12 | **AP-5a.1 QC r3** (`docs/pm/2026-10/qc/AP-5a1-r3.json`): **fail** — back-fill **25 written**; smoke **X1** overlap artefact. |
| 2026-10-12 | PM built **OPS-ARR2** (folds OPS-ARR1): `arr_client.py`, `api_unreachable`, `smoke-ops-arr2.sh`. Tests 301 → 316. |
| 2026-10-12 | **OPS — Sonarr import:** Office S03; host loopback/LAN 000; manual `docker exec sonarr` scan. `handoffs/PM-PASTE-2026-10-12-sonarr-import.md`. |
| 2026-10-12 | PM reviewed the AP-5a.1 r2 back-fill dry run (27 to write): accepted except 2 `minecraft` jobs (Minecraft-server housekeeping, no such kind in current code). r3 on `pm/ap-5a1-r3`: `minecraft` added to `NOT_DOWNLOADS` + test (301 pass). Cursor runs the real back-fill (expect 25), then merges PR #11 (`cursor-prompts/cursor-ap5a1-r3.md`). Next PM build: AP-5a.2. |
| 2026-10-12 | **AP-5a.1 QC r2** (`docs/pm/2026-10/qc/AP-5a1-r2.json`): **pass** — PM test fix `d39f4ea`; 301 unit tests (`huggingface_hub==0.26.2`); Pi/worker deploy + parity; smoke X1–X7 7/7; PR #11 marked ready (not merged). |
| 2026-10-12 | **AP-5a.1 QC r1** (`docs/pm/2026-10/qc/AP-5a1-r1.json`): **fail** — rebase onto `main` ok; `unit.pytest` 300/301 (`test_entry_hf_error_kinds` vs newer `huggingface_hub`); deploy/smokes skipped. |
| 2026-10-12 | PM confirmed AP-UX-1 r2 + AP-4.2 r1 pass (s_second_gap 369 s = 60 + poll + 300; s_granted_state skip covered by unit S4). Split AP-5a into **5a.1** (per-download record on the Pi) and **5a.2** (ai-server catalogue). Built AP-5a.1 on `pm/ap-5a1`: `download_record.py`, `/api/index/*` (search, card, note, export with byte cursor, sources, entries), tombstones on Storage delete and purge, housekeeping kinds no longer journalled, `ABOUT-THIS-DOWNLOAD.md` for GitHub/HF, `rebuild-download-index.py --from-jobs`; 301 tests. Cursor prompt `handoffs/AP-5a1.md`. |
| 2026-10-12 | PM closed AP-UX-1 r2 and AP-4.2 r1 on integrator browser QC forwarded by Finn (`PM-PASTE-2026-10-12-browser-qc.md`). #queueLicenceBar "hidden" was the test view: the queue panel only renders with `?panel=hub` or `?panel=queue`. PRs #7, #8, #9 merged to main; #9 merged before its QC passed (rule restated: merge only after overall = pass). Next PM build: AP-5a per-download index. |
| 2026-10-12 | Finn accepted the Gemma and Llama-3.2-1B licences; Gemma job was picked up by the 10-min re-check. Finn asked for re-checks at 1, 5, 30 min then hourly. PM built **AP-4.2** on `pm/ap-4.2` (schedule, `granted` state fixes "awaiting_licence while running", Licence needed / Approval needed copy, next-check line); 286 tests. Decisions: resume AP-4.1 r3 phase 2 now; close AP-UX-1 r2 on Finn's one-line R5; *arr R0 split to OPS-ARR1. Cursor prompt `handoffs/AP-4.2.md`. |
| 2026-10-12 | **Finn UI validation (Tailscale):** queue GitHub URL → **`escAttr is not defined`**; queue panel **Could not load queue**; `:3000/assets/hub-escape.js` **404** (OPS-HF1). Tried `:3020/hub-form` without slash → 404 JSON; use **`/hub-form/`**. PM paste `handoffs/PM-PASTE-2026-10-12-ui-blocker-ops-hf1.md`. |
| 2026-10-12 | **AP-4.2 QC r1** (`docs/pm/2026-10/qc/AP-4.2-r1.json`): **blocked** — progressive HF gate schedule deployed; schedule smokes pass; Finn gate UI copy pending. |
| 2026-10-12 | **AP-4.2 QC r1** (`docs/pm/2026-10/qc/AP-4.2-r1.json`): **blocked** — gate schedule live; smokes S1–S3 pass; Finn `ui.gate_copy` pending. PR #9. |
| 2026-10-12 | **AP-UX-1 QC r2** (`docs/pm/2026-10/qc/AP-UX-1-r2.json`): **blocked** — smoke R0–R4 pass; Finn one-line R5 pending. |
| 2026-10-12 | PM review of AP-UX-1 r1: R4 root cause was PM code (legacy `capture-folders.json` `magnet` → `nas/inbox` imported as a TV override), not the ai-server mount. Fix on `pm/ap-ux-1`: tv/film fixed to `torrents/`, legacy magnet/website keys dropped, smoke R1 pins tv/film/website paths; 279 tests. F1 closed by OPS-HF1 r2 pass. r1 ran before AP-4.1 r3 (explains live `?v=ux1`). Cursor prompt `handoffs/AP-UX-1-r2.md`. |
| 2026-10-12 | **AP-UX-1 QC r1** (`docs/pm/2026-10/qc/AP-UX-1-r1.json`): **fail** — Pi deploy + presets API + smoke R0–R3 pass; gateway Caddy parity fail; R4 manual tv→inbox HTTP 400 (/mnt/media on ai-server); PR #8 draft; Finn R5 pending. |
| 2026-10-12 | PM implemented **AP-UX-1** on `pm/ap-ux-1`: `download_presets.py` (8 presets, 4 segments), `/api/presets`, `/api/presets/resolve`, jobs store `preset`/`segment`/`destination_source`, Firefox capture + Requests through presets (fixes magnet → `nas/inbox` and Request approve → aria2 for GitHub links), form preset chips + Saves-to + Manually set path, queue segment filter; 241 → 277 tests; `smoke-apux1-presets.sh`. Finding: aria2 already put film `movies/` jobs in `torrents/movies/`. |
| 2026-10-12 | Finn named two pressing items: per-download index (person + machine, delete + nightly updates) and download segments (HF+GitHub, websites, TV, other). Specs extended (AP-UX-1 segments, AP-5 v2 per-download record/deletes, I11–I14); master-document map and Learnings added here. PM starts AP-UX-1 code. |
| 2026-10-12 | PM review: OPS-HF1 r1 fail = glance.yml cache-buster drift only (deploy correctly stopped); repo bumped to `v=20261012hf1`, overwrite of `?v=` diffs authorised. AP-4.1 r2 blocked: PM's Gemma picks are gated manual (and base 9b is 37 GB); rule relaxed, `GATE_REPO=google/gemma-2-9b-it`. #5, #6 merged to `main`; #7 retargeted. Issued `OPS-HF1-r2-AP-4.1-r3.md`. |
| 2026-10-12 | **OPS-HF1 QC r1** (`docs/pm/2026-10/qc/OPS-HF1-r1.json`): **fail** — glance.yml drift (`v=20261012ops1` live vs repo); gateway deploy skipped; `hub-escape.js` 404; worker compile/parity pass. |
| 2026-10-12 | **AP-4.1 QC r2** (`docs/pm/2026-10/qc/AP-4.1-r2.json`): **blocked** — `HF_TOKEN` + worker restart pass; `google/gemma-2-9b` / `-it` both `gated: manual` on HF API (no smoke); MERGE-1 #5/#6 merged to `main`, #7 draft on `main`. |
| 2026-10-12 | Finn: PM picks a ~20 GB gated model (→ `google/gemma-2-9b`), HF token stays active during testing, film inbox OK if existing connections keep working, Cursor does MERGE-1. Prompt `OPS-HF1-AP-4.1-r2.md` updated (Part F merges, `WAIT_S=14400`). |
| 2026-10-12 | PM: Glance queue P0 root-caused (no Caddy route for `hub-escape.js`; gateway files never in manifest/parity) → **OPS-HF1** `4458018`, 241 tests. Restored an indentation-damaged uncommitted `hub-worker.py` in the Mac checkout (patch saved in `.tmp-hub-ui/`). Specs: AP-UX-1 presets, AP-5 index v2, ROADMAP-2026-10. Cursor prompt `handoffs/OPS-HF1-AP-4.1-r2.md` (gateway deploy, worker check, AP-4.1 QC r2). |
| 2026-10-12 | PM implemented **AP-4.1** (one-click gated HF licence, Finn's choice) on `pm/ap-4.1`: gate probe + `awaiting_licence`/`needs_token` waits, `gate-check` endpoint, Hub Licence-needed UI, index `licence_accepted_by`; 217 → 239 tests; `smoke-ap41-gate.sh` 7/7 on a local Hub. One Cursor prompt issued: AP-4 r1b, then AP-4.1 r1. |
| 2026-10-12 | PM review of AP-4 QC r1 (`AP-4-r1.json`): blocked on env only (F1, image `:4` not set); since fixed with Finn's OK. Legacy `hf` downloads had real weights, not LFS pointers (PM inference was wrong). Issued r1b: Pi app reload check, worker restart, smoke + disk checks. Finn's gated-licence requirement specced as AP-4.1. |
| 2026-10-12 | **AP-4.1 QC r1** (`docs/pm/2026-10/qc/AP-4.1-r1.json`): 239 tests, PR #7; Pi gate-check + form UI **pass**; **blocked** on `HF_TOKEN` and gated smoke. |
| 2026-10-12 | **AP-4 QC r1b** (`docs/pm/2026-10/qc/AP-4-r1b.json`): **overall pass** — `hub-form.service` reload, worker restart, URL→`huggingface_repo`, smoke 7/7, `model.safetensors` 453864 B (not LFS). |
| 2026-10-12 | **AP-4 QC r1** (`docs/pm/2026-10/qc/AP-4-r1.json`): 217 tests; draft PR #6 (base `pm/ap-3.1`); Pi/worker parity + image `:4` built; **blocked** on `REPO_ARCHIVER_IMAGE=:4` in hub-worker.env — smoke not run. Legacy hf LFS check: real weights at SmokeTest. |
| 2026-10-12 | PM implemented **AP-4** on `pm/ap-4`: `repo_archive_hf.py` (`huggingface_repo` lane), archiver `:4` `hf_snapshot`, `build_hf_entry` + `scrub_free_text`, form options, archive-root drive fix for legacy `hf`/`github` jobs; 193 → 217 tests; `scripts/smoke-ap4-hf.sh` (7 checks). Cursor round 1 issued. |
| 2026-10-12 | **PM sign-off: AP-3.1 and AP-3 done** (QC r4 overall pass, 0 findings). PR #5 ready for Finn to merge. Next: AP-4 on `pm/ap-4` after the merge. Open P2: stale aria2 gid job stays `running` (no longer blocks lanes). |
| 2026-10-12 | PM review of QC r3b: lane fix proven (Sintel 129 MB). Repo-drain fail root-caused: aria2 returns JSON-RPC errors as HTTP 400, `aria2()` let `HTTPError` escape, `find_resumable_aria2_job()` only caught `RuntimeError`, so every tick died before the repo claims (same cause as r1 F3). Round 4: `aria2()` converts to `RuntimeError`, housekeeping isolated in `main()`; 189 → 193 tests. |
| 2026-10-12 | **AP-3.1 QC r4** (`docs/pm/2026-10/qc/AP-3.1-r4.json`): worker deploy; 193 tests; Sintel smoke 6/6; loop log clean. **overall pass**; PR #5 ready for review; AP-3 §T6 steps 2–3 ticked. |
| 2026-10-12 | **AP-3.1 QC r3b** (`docs/pm/2026-10/qc/AP-3.1-r3b.json`): Sintel `torrent_bytes_rise` **pass**; `repos_drain` / `readme_excerpt` **fail** (stale aria2 gid on smoke torrent; R2/R3 never claimed). PR #5 stays draft. |
| 2026-10-12 | PM review of QC r3: Spoon-Knife and TNAS fixes proven live; no code change. `torrent_bytes_rise` 0 judged swarm-side (claimed at 10 s with 3 repo jobs ahead; r1 showed ~129 MB with Sintel during git/git). Issued r3b: one smoke re-run with Sintel, then PR #5 ready for review. |
| 2026-10-12 | **AP-3.1 QC r3** (`docs/pm/2026-10/qc/AP-3.1-r3.json`): image `:3`, 189 tests; Spoon-Knife 1 MB / 0 pull refs; smoke repo drain **pass**; `torrent_bytes_rise` **fail** (Tears of Steel). |
| 2026-10-12 | AP-3.1 QC r2 reviewed (`AP-3.1-r2.json`): orphan recovery **proven** (S4 job `27d1993819a1`), Hello-World README **pass**, token sampler **pass**. Two real defects: (1) `git clone --mirror` fetched GitHub `refs/pull/*`, so Spoon-Knife `74ad6f30004f` hit the 64 MB cap; (2) one failed TNAS mount check deferred R1 for 120 s and the smoke waited 60 s. Round 3 (`4842a71`): heads+tags bare fetch, image `:3`, `repo_path_ready` re-check, stale-mount clear, smoke `R1_WAIT_S=150`; 183 → 189 tests. Sintel collision = test hygiene (S0 prep check). |
| 2026-10-12 | AP-3.1 QC r1 (`docs/pm/2026-10/qc/AP-3.1-r1.json`, PR #5): 15 pass, 4 fail. Lane fix proven live (torrent claimed 10 s, 129 MB during git/git clone; token absent from `ps`). Fails traced by PM to one root cause: worker restart mid-smoke orphaned Spoon-Knife as `running`, holding the repo slot. Round 2: `recover_orphaned_repo_jobs()` + named containers; 183 tests. F3 stale aria2 gid → P2 backlog. |
| 2026-10-12 | **AP-3.1 QC r1** (`docs/pm/2026-10/qc/AP-3.1-r1.json`): pushed `pm/ap-3.1`, draft PR #5, Pi/worker deploy + parity **0**, image `:2` built; `smoke-ap31-lanes.sh` torrent lane **pass**; `repos_drain`/`readme_excerpt` **fail** (15 min timeout); `deploy.worker_log` **fail** (`hub http 400` aria2 stale gid). |
| 2026-10-12 | Ops closed (DHCP reservation, `HUB_GITHUB_TOKEN`, Kuma, PR #4). PM implemented AP-3.1 on `pm/ap-3.1`: lane-aware claim, `not_before` back-off, Pi keeps `error_display`/`resolved`, token via stdin, README any-name + API fallback, image `:2`, archiver in worker manifest; 146 → 177 tests. Acceptance script `scripts/smoke-ap31-lanes.sh`; Cursor handoff `docs/pm/2026-10/handoffs/AP-3.1.md`. |
| 2026-10-12 | Home ops (`cursor/ops-2026-10-12-home`): `stackrise-pi` → `100.85.42.0`; TNAS `.187` in repo + Pi deploy; parity pi/worker **0**; §T6 step 2 baseline **fail** (torrent error, repo slot). `HUB_GITHUB_TOKEN` still unset. |
| 2026-10-12 | TNAS cable restored, NAS at `.187`; job `694e010971e2` Hello-World done, indexed, idempotent re-queue ok. PM: AP-3 live for manual use but not done (§T6 2 not run; `README.md` missing because the archiver only reads `HEAD:README.md`). Priority AP-3.1 → AP-4. Finn: DHCP reservation, `.186` clean-up, `HUB_GITHUB_TOKEN`. |
| 2026-10-12 | PM reconciliation of Cursor merge + deploy pass: #1/#2 merged, `cursor/ap-3` at `71b7323` (3 commits on `5823319`), AP-3 live on both hosts. **PR #3 GO to merge now**; §T6 blockers are ops. PM found a lane-blind claim starvation bug and dropped `error_display` → AP-3.1 (PM implements). |
| 2026-10-12 | AP-3 reviewed: GO for AP-4. Merge order set: AP-1 → AP-2 → rebase AP-3. §T2 integration tests deferred as fast-follow, not a go-blocker. Deploy steps issued for ai-server worker. |
| 2026-10-12 | Live deploy: Pi + worker manifest rsync; parity worker OK, Pi 22/22; overnight dry-run OK; follow-up commit `9310d1b` (encoding + `ssh -n` in parity script). PM paste: `docs/pm/2026-10/handoffs/PM-PASTE-2026-10-12.md`. |
| 2026-10-11 | AP-1 accepted (54→110 tests, 0 fail). GO for AP-2. GitHub review via offline-intelligence fork PRs / handoff files. |
| 2026-10-11 | PM issued Cursor prompts: audit AP-1/AP-2 with test plan and test reports; GitHub + HF repo archive spec (segmented lane, stars-to-queue, searchable index). |
| 2026-10-12 | Audit handoff pack: AUDIT-BRIEF-2026 + docs 08–14; live probes; dismiss UX on Pi. |
| 2026-10-11 | Claude PM workflow defined; PROJECT-STATE created; user uses Tailscale Hub. |

---

## CONTEXT UPDATE template (for Claude PM)

When appending session log or changing backlog, use this shape in replies:

```markdown
## CONTEXT UPDATE

### Last updated
YYYY-MM-DD

### Decisions changed
- (bullet or "none")

### Backlog changes
- [ ] New item / mark [x] done with one-line note

### Session log entry
| YYYY-MM-DD | what happened |
```
