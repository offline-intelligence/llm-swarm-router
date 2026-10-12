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
| 5 | TNAS offline defer | **pass (defer path)** — job stays `queued`, progress note `TNAS offline, will retry` (2026-10-12 home) |

### Home LAN ops (2026-10-12, evening)

| Check | Result |
|-------|--------|
| `mount-tnas-docker.sh` | **fail** — `192.168.50.186` unreachable (CIFS 113) |
| LAN sweep from ai-server | Up: `.1 .19 .63 .65 .138 .175 .222` — **no `.186`**, no TOS `:8181` |
| Hub `GET /api/machines` | `tnas`: `reachable: false`, `power_on: false` |
| Archiver image | **built** `bucket-hub-repo-archiver:1` on ai-server |
| `HUB_GITHUB_TOKEN` | **still missing** in `hub-worker.env` |
| §T6 steps 3–4 | **blocked** until TNAS mount + successful `github_repo` `done` |

### §T6 success (2026-10-12, TNAS cable restored)

| Step | Result |
|------|--------|
| 1 | Worker **parity ok**; TNAS mounted at `//192.168.50.187/public` → `/mnt/tnas` |
| 2 | **Not run** (parallel torrent + repo) |
| 3 | Job **`694e010971e2`**: `done`; `github-daily/2026-10-12/octocat__Hello-World/` — `repo.git/`, provenance + tags sidecars; no `.partial-*` |
| 4 | Re-queue Hello-World same day → **`done`** (idempotent) |
| 5 | Defer path validated earlier when unmounted |

**Ops note:** NAS DHCP moved **`.186` → `.187`**; `TNAS_HOST` updated in `~/homelab/.env` on ai-server. Top-level `README.md` not in folder (mirror layout — PM to confirm spec).

Enqueue smoke: `POST http://100.85.42.0:3000/api/jobs` with `kind: github_repo`, `octocat/Hello-World` → **ok**, `worker: repo`.

### §T6 home re-run (2026-10-12, ops branch)

| Item | Command / check | Exit / timing | Pass? |
|------|-----------------|---------------|-------|
| **Step 1 — parity** | `./scripts/verify-deploy-parity.sh pi` (before deploy: mismatch `machines_ctl.py`, `glance.yml`) | after rsync + `hub-form` restart: **0** | **pass** |
| **Step 1 — worker** | `./scripts/verify-deploy-parity.sh worker` | **0** (before and after) | **pass** |
| **Step 2 — parallel** | QC r3 `smoke.repos_drain` + `smoke.torrent_claimed_60s` | Repo lane + torrent claim **pass**; `torrent_bytes_rise` **fail** (swarm) — [AP-3.1-r3.json](../pm/2026-10/qc/AP-3.1-r3.json) | **partial** |
| **Step 3 — README / Spoon-Knife** | QC r3 `live.spoon_knife_done` + `smoke.readme_excerpt` | Spoon-Knife 1 MB, no pull refs; Hello-World README | **pass** (QC r3) |
| **Task 6 — heartbeat** | `GET /api/status` `heartbeat_age_s` ~10s; worker log tail has historical `heartbeat failed` / `loop error` bursts | Pi reachable now; not blocking single-repo smokes | **note** |

§T6 step 2 commands:

```bash
# torrent (failed — CD URL or VPN)
curl -s -X POST http://100.85.42.0:3000/api/jobs -H 'Content-Type: application/json' \
  -d '{"kind":"http","url":"https://cdimage.debian.org/.../debian-13.2.0-amd64-netinst.iso.torrent",...}'

# repo (queued while slot busy)
curl -s -X POST http://100.85.42.0:3000/api/jobs -H 'Content-Type: application/json' \
  -d '{"kind":"github_repo","url":"https://github.com/octocat/Spoon-Knife",...}'
```
