# Changelog

## 2026-10-12 — AP-5a.1 per-download record (PM)

**Why:** Finn wants every download indexed for a person and for a machine, and the index to change when something is deleted. **What changed:** `download_record.py` merges the Pi journal (entries, note edits, delete tombstones); `/api/index/search`, `/card`, `PATCH` note, `/export?since=<cursor>`, `/sources`, `POST /entries`; finished jobs record `segment`/`preset`/`saves_to`; Storage delete and cancel + purge mark records `deleted`; deletes and syncs no longer appear as downloads; GitHub/HF archives get `ABOUT-THIS-DOWNLOAD.md`; `scripts/rebuild-download-index.py --from-jobs`. Tests 286 → 301. Doc `homelab/bucket-hub/docs/DOWNLOAD-INDEX.md`.

Deployed 2026-10-12, QC r2 **pass** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-5a1-r2.json`).

## 2026-10-12 — AP-4.2 Hugging Face access re-check schedule (PM)

**Why:** Finn wanted the Hub to re-check a gated model soon after he accepts, not every 10 min. **What changed:** re-checks after 1, 5 and 30 min, then hourly (`HF_GATE_SCHEDULE_S`); Check now kept and does not reset the schedule; `gate.state = granted` while the download runs; manual gates say "Approval needed" / "Request access"; cards and the queue bar show "Next automatic check in N min". Tests 279 → 286. Spec `homelab/bucket-hub/docs/pm/2026-10/AP-4.2-gate-schedule.md`.

## 2026-10-12 — AP-4.2 HF access re-check schedule (PM)

Progressive gate gaps (1, 5, 30 min, then hourly), `granted` state while downloading, Licence vs Approval copy. Branch `pm/ap-4.2` on `pm/ap-ux-1`.

QC r1 **pass** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-4.2-r1.json`): worker/Pi/gateway deploy + schedule smokes pass; gate card + queue licence bar verified (`?panel=hub`).

## 2026-10-12 — AP-UX-1 download presets and segments (PM)

**Why:** Finn wants separate download segments with pre-defined paths. The Download tab asked for a drive and folder for every type, even where the server ignored them, and the same magnet landed in different places from the form (`torrents/`) and from Firefox (`nas/inbox`).

**What changed:**

- New `download_presets.py`: 8 presets in 4 segments (TV & film · Repo archive · Websites · Other), resolved server-side against the library with fallbacks; `capture-folders.json` still overrides.
- `GET /api/presets`, `POST /api/presets/resolve`; `POST /api/jobs` takes `preset` / `manual_path` and stores `preset`, `segment`, `destination_source`; `GET /api/jobs?segment=`.
- Firefox capture and Requests (link mode and approve) resolve through presets.
- Hub: Download type chips, "Saves to" line, Drive/Folder only behind **Manually set path**, Type select removed, queue segment filter.
- Tests 241 → 277; `scripts/smoke-apux1-presets.sh` (checks Sonarr/Radarr/Jellyfin paths are unchanged before vs after).

Deployed 2026-10-12, QC r1 **fail** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-UX-1-r1.json`): Pi presets deploy ok; gateway Caddyfile parity fail (OPS-HF1 not live); smoke R4 manual path blocked on /mnt/media mount. Finn Tailscale UI check: `escAttr is not defined` until `:3000/assets/hub-escape.js` is deployed (PM paste `handoffs/PM-PASTE-2026-10-12-ui-blocker-ops-hf1.md`).

Round 2 (PM): QC r1 R4 was a PM bug. The shipped `capture-folders.json` `magnet` → `nas/inbox` key overrode the TV preset; TV and film are now fixed to Expansion HDD `torrents/`, legacy `magnet`/`website` keys dropped, smoke R1 pins the paths. Tests 277 → 279. Cursor prompt `homelab/bucket-hub/docs/pm/2026-10/handoffs/AP-UX-1-r2.md`.

QC r2 **pass** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-UX-1-r2.json`): Pi deploy + smoke R0–R4 pass; integrator browser QC (Finn forwarded, PM accepted).

## 2026-10-12 — OPS-HF1 gateway serves `hub-escape.js` (PM)

**Why:** the Glance queue failed with `escHtml is not defined`: AP-1's shared `/assets/hub-escape.js` was served by the Hub app but the `hub-gateway` Caddyfile had no route for it. The gateway files (`Caddyfile`, `glance.yml` in `~/homelab/glance/`) were never in the deploy manifest, so parity checks could not catch it.

**What changed:** Caddy route for `/assets/hub-escape.js`; `[gateway]` section in `scripts/deploy-manifest.txt`; `verify-deploy-parity.sh gateway`; test that every `/assets/` file referenced by a page is routed by the gateway and served by `app.py`. Tests 239 → 241. Also: specs `AP-UX-1-download-presets.md`, `AP-5-index-architecture-v2.md`, `ROADMAP-2026-10.md`.

Deployed 2026-10-12, QC r1 **fail** (`homelab/bucket-hub/docs/pm/2026-10/qc/OPS-HF1-r1.json`): glance.yml live drift blocked copy; `hub-escape.js` still 404 on :3000; worker parity ok.

## 2026-10-12 — AP-4.1 gated Hugging Face repos: one-click licence (PM)

**Packet:** AP-4.1 (`pm/ap-4.1`, on top of `pm/ap-4`), written by the PM; Cursor deploys.

**Why:** pasting HF links is the main use case (Finn). A gated model ended in "accept the licence and retry". Hugging Face has no user-side accept API, so Finn chose one click: the Hub waits and downloads by itself after he accepts.

**What changed:**

- Gated repos are probed after metadata (`HEAD …/resolve/<sha>/<file>`, token over stdin). No access → job `queued` with a `gate` record and `not_before` (`HF_GATE_RECHECK_S`, 600 s); no `HF_TOKEN` → `needs_token`; expires after `HF_GATE_MAX_WAIT_H` (168 h).
- `POST /api/jobs/{id}/gate-check` ("Check now"); `PATCH` accepts `gate` (null clears); Retry clears it.
- Hub UI: "Licence needed" pill, Accept licence + Check now on the job, "Waiting for a licence (N)" bar.
- Index entries: `licence_accepted_by`, `gate_wait_s`.
- New `scripts/smoke-ap41-gate.sh` (two phases around Finn's click). Tests: 217 → 239 passed.

Deployed 2026-10-12, QC r1 **blocked** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-4.1-r1.json`): integrate + deploy ok; `HF_TOKEN` unset; gated smoke not run.

QC r2 **blocked** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-4.1-r2.json`): `HF_TOKEN` present, worker restarted; PM `GATE_REPO` list exhausted (`gated: manual`); smoke not run; PR #7 retargeted to `main`, not merged.

## 2026-10-12 — AP-4 Hugging Face repo archive (PM)

**Packet:** AP-4 (`pm/ap-4`), written by the PM; Cursor deploys.

**Why:** Hugging Face models and datasets had no archive lane: the only option was the legacy `hf` job, a shallow `git clone` to a library drive with no index entry, no size guard and (inferred from code) LFS pointers instead of weights. Live bug found on the way: legacy `hf` / `github` jobs were created without a `destination_path`.

**What changed:**

- New `huggingface_repo` kind and `repo_archive_hf.py`: models and datasets (Spaces rejected), metadata pre-check, `prefer_safetensors` / `allow_patterns` / `ignore_patterns`, `max_size_mb` (pre-check, post-check at 110 %), snapshot pinned to the revision sha, model card as `README.md`, index entry (`source_id` `hf:<type>/<id>`, `file_summary`, licence, pipeline tag) and sidecars, dedupe unless `refresh`.
- Archiver image `:4`: `hf_snapshot` via `huggingface_hub==0.26.2`; `HF_TOKEN` (optional, gated models) via env only. Readable errors for not found / gated.
- `repo_runner`: `run_hf_snapshot`, `ArchiverError` kinds; Docker runner parses the archiver's JSON result line.
- `index_writer`: `build_hf_entry`, `file_summary`, `scrub_free_text` (also on GitHub readme excerpts).
- `app.py`: drive check skipped only for archive-root and repo-meta kinds (restores `destination_path` for legacy `hf`/`github`); huggingface.co URLs detect `huggingface_repo`.
- `form.html`: "GitHub repo (TNAS archive)", "Hugging Face repo (TNAS archive)", "Hugging Face files (to drive)".
- `repo_archive_hf.py` added to both deploy manifests. New `scripts/smoke-ap4-hf.sh`. Tests: 193 → 217 passed.

Deployed 2026-10-12, QC r1 **blocked** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-4-r1.json`): integrate + parity + image `:4` ok; `REPO_ARCHIVER_IMAGE=:4` not set; smoke not run.

QC r1b **pass** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-4-r1b.json`): Pi `hub-form.service` reload; worker restart; `smoke-ap4-hf.sh` 7/7; real weights on TNAS.

## 2026-10-12 — AP-3.1 repo lane fast-follow (PM)

**Packet:** AP-3.1 (`pm/ap-3.1`), written by the PM; Cursor deploys.

**Why:** the worker claimed jobs lane-blind, so a queued repo job could be claimed and bounced by the aria2 loop every tick and starve torrents; TNAS defers had no back-off; the Pi dropped worker `error_display`/`resolved`; the GitHub token was visible in `ps`; `README.md` was missing for repos whose README is not literally `README.md`.

**What changed:**

- `POST /api/jobs/claim` accepts optional `{"lane": …}` (a `_job_kind_bucket`); `hub-worker.py` passes `aria2`, `video`, `repo`, `repo_meta` from its dispatch loops. No body keeps the old claim.
- Jobs with a future `not_before` are skipped by every claim; TNAS-offline defer sets it (`HUB_REPO_DEFER_S`, default 120 s).
- `JobUpdate` accepts `error_display`, `resolved`, `not_before`; stored `error_display` shows when there is no raw error and is cleared on `running`/`done`.
- `gluetun_http_json` sends `Authorization` over stdin (`docker run -i`, `curl -H @-`), never argv.
- Archiver image `:2`: README picked case-insensitively from `git ls-tree HEAD` and saved as `README.md`; worker falls back to the GitHub `/readme` API.
- `docker/repo-archiver/*` added to the `[worker]` deploy manifest.
- New `scripts/smoke-ap31-lanes.sh` (§T6 step 2, adversarial order). Tests: 146 → 177 passed.

Deployed 2026-10-12, QC r1 **fail** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r1.json`): Pi/worker deploy + parity ok; §T6 adversarial torrent lane **pass**; repo drain/readme smoke timeout; worker log had aria2 `hub http 400` lines.

QC r2 **fail** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r2.json`): orphan recovery proven on deliberate restart; Hello-World README on TNAS; full smoke not clean (stale Sintel + TNAS defer).

QC r3 **fail** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r3.json`): archiver `:3` Spoon-Knife 1 MB / no `refs/pull`; full repo drain pass; `smoke.torrent_bytes_rise` fail (Tears of Steel swarm).

QC r3b **fail** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r3b.json`): Sintel `torrent_bytes_rise` pass; `smoke.repos_drain` fail (stale aria2 gid on smoke torrent).

Round 4 (PM): `aria2()` raises `RuntimeError` for aria2's HTTP 400 JSON-RPC errors (they were escaping as `HTTPError` and logged as `hub http 400`); aria2 housekeeping in the worker loop is isolated so a stale gid can no longer skip the video and repo claims. Tests 189 → 193.

QC r4 **pass** (`homelab/bucket-hub/docs/pm/2026-10/qc/AP-3.1-r4.json`): worker deploy; full Sintel smoke 6/6; PR #5 ready for review.

Round 3 (PM): archiver image `:3` fetches branches and tags only (no GitHub `refs/pull/*`, which made Spoon-Knife exceed its cap); worker re-checks the TNAS mount once (`HUB_REPO_RECHECK_S`, 5 s) before deferring a repo job and clears a stale mark once the mount answers; defer note names the reason; smoke R1 waits 150 s. Tests 183 → 189.

## 2026-10-12 — Home ops: TNAS `.187`, Pi SSH, deploy

**Packet:** ops (`cursor/ops-2026-10-12-home`).

**Why:** DHCP drift and broken `stackrise-pi` DNS blocked parity and Hub machine probes.

**What changed:**

- Tracked TNAS URLs/IPs `192.168.50.186` → `192.168.50.187` (`machines_ctl.py`, `glance.yml`, smoke scripts, `machines.example.json`).
- Pi manifest redeployed; `verify-deploy-parity.sh pi` exit 0; Glance hub iframe `?v=20261012ops1`.
- Mac `~/.ssh/config`: `stackrise-pi` → Tailscale `100.85.42.0` (local, not in repo).
- §T6 step 2 baseline recorded **fail** in `AP-3-test-report.md` (torrent error + repo slot).
- Follow-up (Finn, same day): ASUS RT-AX57 DHCP reservation `tnas` → `.187`; `HUB_GITHUB_TOKEN` set on ai-server; Uptime Kuma TNAS monitor → `http://192.168.50.187:8181/`.

## 2026-10-12 — AP-3 deploy reconciliation (PM)

**Packet:** AP-3 — PM review of the merge + worker deploy pass.

**Why:** Record the merge decision for PR #3 and the open §T6 blockers so git, docs and production agree.

**What changed (docs only):**

- Confirmed: PR #1 and #2 merged into `hub/audit-handoff-2026-10`; `cursor/ap-3` is `71b7323`, three commits on `5823319`; AP-3 live on Pi and worker.
- Decision: **PR #3 merges now**. §T6 is a deploy gate, not a merge gate, because the code is already deployed and the gaps are ops-only.
- §T6 open: worker → Pi heartbeat/claim timeouts, TNAS unmounted, `bucket-hub-repo-archiver:1` not built, `HUB_GITHUB_TOKEN` and repo env unset.
- AP-3.1 fast-follow logged in `PROJECT-STATE.md`: lane-blind `claim_next()` lets a TNAS-deferred `github_repo` job starve queued torrents; `error_display` dropped by Pi `JobUpdate`; §T2 argv tests; token out of `docker run` argv; archiver build context in deploy path.

## 2026-10-12 — AP-3 (Bucket-HUB repo lane)

**Packet:** AP-3 — GitHub repo archive lane (`github_repo`).

**Why:** Repo clones must not share aria2 claim slots or block torrent supervision. Archives live on the TNAS under `HUB_REPO_ARCHIVE_ROOT` with provenance in `index_writer.py`.

**What changed:**

- Pi: `repo` / `repo_meta` claim buckets, `HUB_SLOT_REPO`, `JobCreate.options`, `GET /api/repo-lane`, `github_repo` jobs without drive/folder.
- Worker: `_repo_pool`, `run_github_repo_job`, startup archive-root guard, legacy `github`/`hf` on repo lane.
- New modules: `repo_archive_paths.py`, `repo_archive_github.py`, `repo_runner.py`, `hub_worker.py` (`safe_clone`), `docker/repo-archiver/`.
- `index_writer.build_github_entry` for repo provenance records.

**Dependencies:** none added to `requirements-hub-form.txt` (archiver image pins its own Python deps).

## 2026-10-12 — AP-1/AP-2 merge + AP-3 rebase and worker deploy

**Packet:** merge order (PR #1, #2 on `offline-intelligence`), rebase `cursor/ap-3` onto `hub/audit-handoff-2026-10`, deploy worker manifest to `ai-server-ts`.

**Why:** PM-approved merge order; production worker must run the same bytes as git before live §T6.

**What changed (ops):**

- Merged offline-intelligence PR #1 (AP-1) and #2 (AP-2) into `hub/audit-handoff-2026-10`.
- Rebased and force-pushed `cursor/ap-3`; **146 passed** pytest.
- Rsynced all `[worker]` manifest paths to `~/homelab/scripts/`; `verify-deploy-parity.sh worker` **exit 0** after restart.
- Pi hub-form rsynced for AP-3 API (`GET /api/repo-lane`, `github_repo` enqueue); `hub-form` **active**.

**Blockers for full §T6:** `HUB_GITHUB_TOKEN` not set in `hub-worker.env`; TNAS not mounted on ai-server; `bucket-hub-repo-archiver` image not built; worker log shows Pi heartbeat timeouts (jobs stay `queued`).

## 2026-10-12 — Home LAN TNAS ops (§T6 continued)

**Ops:** Archiver image built; worker env has `HUB_REPO_ARCHIVE_ROOT` / `REPO_ARCHIVER_IMAGE`; worker↔Pi reachability OK via `HUB_URL`. **TNAS still absent at `192.168.50.186`** (LAN scan + CIFS + TOS :8181). Repo jobs correctly defer with TNAS offline. Docs: `REPO-ARCHIVE.md` (`HUB_URL`), `PM-PASTE-2026-10-12-home-tnas.md`.

## 2026-10-12 — TNAS online, §T6 Hello-World pass

**Ops:** Ethernet restored; NAS at **`192.168.50.187`**; `TNAS_HOST` updated on ai-server; CIFS mount + `repo-archive/` created. `github_repo` job `694e010971e2` completed; index line on Pi; idempotent re-queue same day **done**. `HUB_GITHUB_TOKEN` still optional for public repos. PM paste: `PM-PASTE-2026-10-12-tnas-success.md`.
