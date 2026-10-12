# Changelog

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
