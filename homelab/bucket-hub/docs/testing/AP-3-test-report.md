# AP-3 test report

## Run log

```bash
cd homelab/bucket-hub && PYTHONPATH=. uv run --with pytest pytest tests/ -q
```

| When | Result |
|------|--------|
| Before (AP-2) | 124 passed |
| After (AP-3) | 146 passed in 3.1s |

## Automated tests (new)

| File | Coverage |
|------|----------|
| `test_repo_lane.py` | §T1 lane separation + `/api/repo-lane` |
| `test_repo_archive_paths.py` | §T2 paths, slug, partial guard |
| `test_repo_archive_github.py` | §T2 mount defer, idempotent, clone, size cap, provenance |

## Manual smoke (§T6 steps 1–5)

| Step | Command / check | Result (2026-10-12 deploy) |
|------|-----------------|----------------------------|
| 1 | `./scripts/verify-deploy-parity.sh worker` after rsync | **pass** (exit 0, all OK) |
| 1 | `./scripts/verify-deploy-parity.sh pi` | **fail** — `stackrise-pi` resolves `raspberrypi.local` on Mac; use Tailscale rsync to `bucket@100.85.42.0` (manifest applied; `app.py` sha256 matches local) |
| 2 | Torrent + parallel `github_repo` | **not run** — worker heartbeat to Pi timing out; job `c8a5b6f8b306` stayed `queued` |
| 3 | TNAS folder + sidecars | **blocked** — `mountpoint /mnt/tnas` **no**; no `repo-archiver` image on worker |
| 4 | Re-queue same repo | **not run** (depends on step 3) |
| 5 | TNAS offline defer | **implicit** — TNAS already offline; defer path not exercised end-to-end |

Enqueue smoke: `POST http://100.85.42.0:3000/api/jobs` with `kind: github_repo`, `octocat/Hello-World` → **ok**, `worker: repo`.
