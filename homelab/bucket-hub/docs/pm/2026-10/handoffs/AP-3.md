## Handoff to PM

**Packet:** AP-3  
**Branch:** cursor/ap-3 (base: hub/audit-handoff-2026-10)  
**PR:** https://github.com/offline-intelligence/llm-swarm-router/pull/3  

**Files changed:**

- `CHANGELOG.md`
- `homelab/bucket-hub/app.py` — repo/repo_meta buckets, `GET /api/repo-lane`, `github_repo` create path
- `homelab/bucket-hub/hub-worker.py` — `_repo_pool`, repo lane dispatch, archive root guard
- `homelab/bucket-hub/hub_worker.py` — `safe_clone` re-export for smoke imports
- `homelab/bucket-hub/job_kinds.py` — `REPO_KINDS`, dispatch route `repo` / `repo_meta`
- `homelab/bucket-hub/index_writer.py` — `build_github_entry`, `github_repo` kind fields
- `homelab/bucket-hub/repo_archive_paths.py`, `repo_archive_github.py`, `repo_runner.py`
- `homelab/bucket-hub/docker/repo-archiver/` — Dockerfile + entrypoint
- `homelab/bucket-hub/scripts/deploy-manifest.txt`
- `homelab/bucket-hub/docs/api/README.md`, `docs/REPO-ARCHIVE.md`, `docs/testing/AP-3-test-report.md`
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`

**Tests added:** (all pass)

| File | Notes |
|------|--------|
| `tests/test_repo_lane.py` | §T1 lane separation, `/api/repo-lane` |
| `tests/test_repo_archive_paths.py` | §T2 paths, slug, partial guard |
| `tests/test_repo_archive_github.py` | §T2 mount defer, idempotent day, clone, size cap, secret scan |

Full suite: **146 passed** (`124` AP-2 baseline + **22** new).

**Dependencies added:** none (`requirements-hub-form.txt` unchanged; archiver image owns its deps).

**CHANGELOG entry:**

> ## 2026-10-12 — AP-3 (Bucket-HUB repo lane)
>
> **Packet:** AP-3 — GitHub repo archive lane (`github_repo`).
>
> **Why:** Repo clones must not share aria2 claim slots or block torrent supervision. Archives live on the TNAS under `HUB_REPO_ARCHIVE_ROOT` with provenance in `index_writer.py`.
>
> **What changed:**
>
> - Pi: `repo` / `repo_meta` claim buckets, `HUB_SLOT_REPO`, `JobCreate.options`, `GET /api/repo-lane`, `github_repo` jobs without drive/folder.
> - Worker: `_repo_pool`, `run_github_repo_job`, startup archive-root guard, legacy `github`/`hf` on repo lane.
> - New modules: `repo_archive_paths.py`, `repo_archive_github.py`, `repo_runner.py`, `hub_worker.py` (`safe_clone`), `docker/repo-archiver/`.
> - `index_writer.build_github_entry` for repo provenance records.
>
> **Dependencies:** none added to `requirements-hub-form.txt` (archiver image pins its own Python deps).

**SSH smoke output:**

```text
$ ssh -i ~/.ssh/id_ed25519_pi bucket@100.85.42.0 'hostname; systemctl --user is-active hub-form.service'
raspberrypi
active

$ ssh bucket@100.112.168.40 'hostname; systemctl --user is-active hub-worker.service'
Permission denied, please try again.
Permission denied, please try again.
bucket@100.112.168.40: Permission denied (publickey,password).

$ ssh ai-server-ts 'hostname; systemctl --user is-active hub-worker.service'
ai-server
activating

$ cd homelab/bucket-hub && ./scripts/verify-deploy-parity.sh worker
MISMATCH hub-worker.py local=ac0ec6b18248aa99448947b5704a616d69c9e348c4bdde1c3a7668d88e1e6309 remote=d15bbceb6c0c03332ae27e1dceddae8e04527979b099a4f543ff170b960746ff
MISSING_REMOTE hub_worker.py (ai-server-ts:~/homelab/scripts/hub_worker.py)
OK job_health.py
OK download_destinations.py
MISMATCH index_writer.py local=a5485597bb59773703d681f567b6f467302c7b4aae86732238a5ab7b2bf23c9c remote=e4c93e887bd805c7e3a7766f7678f9a4821a127b72963226061b7c6b2323f793
MISMATCH job_kinds.py local=e60cfd3401817251c0b53a21df7f04a646f7cadb97a7805e954557cf290db7c1 remote=effb6f96955650ecb5ae16edf96b9f1d533311918913f6c95ae3dc72b9a23b12
MISSING_REMOTE repo_archive_paths.py (ai-server-ts:~/homelab/scripts/repo_archive_paths.py)
MISSING_REMOTE repo_archive_github.py (ai-server-ts:~/homelab/scripts/repo_archive_github.py)
MISSING_REMOTE repo_runner.py (ai-server-ts:~/homelab/scripts/repo_runner.py)
OK hub_torrent_parse.py
OK media_pipeline.py
OK torrent_indexer_catalog.py
OK torrent-indexers-catalog.json
parity failed for worker
exit:1
```

**Decisions made:**

- Branch `cursor/ap-3` includes AP-1/AP-2 history (not rebased onto `hub/audit-handoff-2026-10` alone) so `index_writer.py` and 146 tests exist; PR diff vs handoff branch is large until AP-1/2 merge.
- `github` / `hf` legacy kinds route to repo lane (not aria2).
- Metadata fetch injected via `configure_repo_archive(fetch_metadata=...)` using `gluetun_http_json` + `HUB_GITHUB_TOKEN` in worker (tests use fake fetcher).
- Not all §T2 cases from the spec are implemented yet (e.g. mirror argv gluetun integration test, concurrent partial cleanup) — core path + idempotency covered.

**Open questions:**

- Merge order: rebase AP-3 onto `main` after AP-1/AP-2 land, or squash-merge stack?
- Finn: rsync worker manifest, `docker build -t bucket-hub-repo-archiver:1 docker/repo-archiver`, set `HUB_REPO_ARCHIVE_ROOT` / `REPO_ARCHIVER_IMAGE` in `hub-worker.env`, confirm TNAS mount — then re-run parity and §T6 live smokes.
- Worker was `activating` during smoke; confirm `active` before enqueueing first `github_repo` job.

---

## Post-merge deploy (2026-10-12, Cursor)

**Merges:** offline-intelligence PR #1 (AP-1) and #2 (AP-2) merged into `hub/audit-handoff-2026-10`. `cursor/ap-3` rebased onto that branch and force-pushed (`591d49a`).

**Pytest (after rebase):**

```text
146 passed, 67 warnings in 3.06s
```

**hub-worker service:**

```text
$ ssh ai-server-ts 'systemctl --user is-active hub-worker'
activating   # before deploy wait loop
try 4: active   # after ~12s
$ ssh ai-server-ts 'systemctl --user restart hub-worker && systemctl --user is-active hub-worker'
active
```

**HUB_GITHUB_TOKEN:** not present in `~/homelab/scripts/hub-worker.env` (no `GITHUB_TOKEN` / `HUB_GITHUB_TOKEN` lines). Add before live clone smokes.

**Parity — worker BEFORE rsync:**

```text
MISMATCH hub-worker.py ...
MISSING_REMOTE hub_worker.py ...
MISMATCH index_writer.py ...
MISMATCH job_kinds.py ...
MISSING_REMOTE repo_archive_paths.py ...
MISSING_REMOTE repo_archive_github.py ...
MISSING_REMOTE repo_runner.py ...
parity failed for worker (exit 1)
```

**Parity — worker AFTER rsync + restart:**

```text
OK hub-worker.py
OK hub_worker.py
OK job_health.py
OK download_destinations.py
OK index_writer.py
OK job_kinds.py
OK repo_archive_paths.py
OK repo_archive_github.py
OK repo_runner.py
OK hub_torrent_parse.py
OK media_pipeline.py
OK torrent_indexer_catalog.py
OK torrent-indexers-catalog.json
parity ok worker (exit 0)
```

**§T6 (steps 1–5):** see `docs/testing/AP-3-test-report.md` table. Pi API live (`GET /api/repo-lane`); enqueue `github_repo` ok; worker could not claim (Pi heartbeat timeouts in log). TNAS unmounted; archiver image not built.

**Finn follow-up:** fix `~/.ssh/config` `Host stackrise-pi` → `100.85.42.0`; add `HUB_GITHUB_TOKEN`; mount TNAS; `docker build -t bucket-hub-repo-archiver:1` on ai-server; restore Pi↔worker connectivity; re-run §T6 steps 2–5.
