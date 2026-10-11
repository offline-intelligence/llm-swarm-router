# Changelog

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
