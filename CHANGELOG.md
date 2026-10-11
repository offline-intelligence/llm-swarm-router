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
