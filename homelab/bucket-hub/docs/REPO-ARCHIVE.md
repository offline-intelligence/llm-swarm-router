# Repo archive (GitHub / HF)

Operator notes for the TNAS repo lane (AP-3+).

## Layout

- Root: `HUB_REPO_ARCHIVE_ROOT` (default `/mnt/tnas/repo-archive`)
- GitHub dailies: `github-daily/YYYY-MM-DD/owner__repo/`
- Work in progress: `.partial-<job_id>/` inside the dated folder (atomic rename on success)

## Worker env (ai-server)

File: `~/homelab/scripts/hub-worker.env` (plus `~/homelab/.env` for CIFS creds).

| Variable | Purpose |
|----------|---------|
| `HUB_URL` | Pi Hub base URL(s), comma-separated (e.g. `http://192.168.50.138:3020,http://100.85.42.0:3020`). **Not** `HUB_BASE_URL` — `hub-worker.py` only reads `HUB_URL`. |
| `HUB_WORKER_TOKEN` | Must match Pi `hub-form` for `POST /api/worker/heartbeat` and job claim. |
| `HUB_REPO_ARCHIVE_ROOT` | TNAS path (default `/mnt/tnas/repo-archive`) |
| `HUB_SLOT_REPO` | Concurrent repo downloads (default `1`) |
| `HUB_GITHUB_TOKEN` | GitHub API + clone auth via Gluetun (recommended; public repos may work without) |
| `REPO_ARCHIVER_IMAGE` | `bucket-hub-repo-archiver:3` from AP-3.1 r3 (`:2` used `clone --mirror` and pulled `refs/pull/*`; `:1` only reads `HEAD:README.md`) |
| `HUB_REPO_DEFER_S` | Seconds a job waits before re-claim after "TNAS offline, will retry" (default `120`) |
| `HUB_REPO_RECHECK_S` | Seconds the worker waits to re-check the archive mount before it defers a job (default `5`) |

CIFS mount: `~/homelab/scripts/mount-tnas-docker.sh` reads `TNAS_HOST`, `TNAS_SHARE`, `TNAS_USER`, `TNAS_PASSWORD` from `~/homelab/.env`. **Current TNAS LAN host:** `192.168.50.187` (`TNAS_HOST` on ai-server). **DHCP reservation:** done 2026-10-12 (ASUS RT-AX57, `tnas` → `.187`).

Build image:

```bash
cd homelab/bucket-hub
docker build -t bucket-hub-repo-archiver:3 docker/repo-archiver
```

## Claim lanes (AP-3.1)

Each worker dispatch loop claims with `POST /api/jobs/claim {"lane": "aria2" | "video" | "repo" | "repo_meta"}`, so a loop never claims a job it would have to put back. No body (or `{}`) keeps the old any-lane claim. A job with `not_before` in the future is skipped by every claim.

## What is archived

`repo.git` is a bare repo holding **branches and tags only** (`+refs/heads/*`, `+refs/tags/*`), with `HEAD` set to the remote default branch. GitHub's `refs/pull/*` are not fetched: on popular repos they carry thousands of fork commits that the API `size` does not count (AP-3.1 QC r2: Spoon-Knife blew a 64 MB cap). To refresh an archive by hand: `git --git-dir repo.git fetch --prune origin`.

## TNAS readiness

Before a repo job is deferred, the worker re-checks the mount once after `HUB_REPO_RECHECK_S`, and first clears a "stale" mark if the mount answers a `stat` again. The deferred job's `progress.note` carries the reason, e.g. `TNAS offline, will retry (NAS is not mounted)`.

## README.md

The archiver copies the top-level README whatever its name (`README`, `README.md`, `.rst`, `.txt`, …, case-insensitive) and always saves it as `README.md` beside `repo.git`. If none is written, the worker falls back to `GET /repos/{owner}/{repo}/readme`. A repo with no README at all finishes `done` without one.

## Deploy

Rsync worker + Pi manifest sets; restart `hub-worker` and `hub-form`; run `scripts/verify-deploy-parity.sh` on both hosts.

After TNAS mount:

```bash
ssh ai-server-ts 'bash ~/homelab/scripts/mount-tnas-docker.sh && mkdir -p /mnt/tnas/repo-archive && mountpoint /mnt/tnas'
```

Archiver image (on ai-server):

```bash
# docker/repo-archiver/* is in the [worker] manifest set, so the normal worker rsync puts it at
# ~/homelab/scripts/docker/repo-archiver/ and verify-deploy-parity.sh worker checks it.
ssh ai-server-ts 'cd ~/homelab/scripts/docker/repo-archiver && docker build -t bucket-hub-repo-archiver:3 .'
```
