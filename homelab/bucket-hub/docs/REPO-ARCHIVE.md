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
| `REPO_ARCHIVER_IMAGE` | e.g. `bucket-hub-repo-archiver:1` |

CIFS mount: `~/homelab/scripts/mount-tnas-docker.sh` reads `TNAS_HOST`, `TNAS_SHARE`, `TNAS_USER`, `TNAS_PASSWORD` from `~/homelab/.env`. **Current TNAS LAN host:** `192.168.50.187` (`TNAS_HOST` on ai-server). **DHCP reservation:** pending Finn (router) so the address does not drift again.

Build image:

```bash
cd homelab/bucket-hub
docker build -t bucket-hub-repo-archiver:1 docker/repo-archiver
```

## Deploy

Rsync worker + Pi manifest sets; restart `hub-worker` and `hub-form`; run `scripts/verify-deploy-parity.sh` on both hosts.

After TNAS mount:

```bash
ssh ai-server-ts 'bash ~/homelab/scripts/mount-tnas-docker.sh && mkdir -p /mnt/tnas/repo-archive && mountpoint /mnt/tnas'
```

Archiver image (on ai-server):

```bash
rsync -av homelab/bucket-hub/docker/repo-archiver/ ai-server-ts:~/homelab/docker/repo-archiver/
ssh ai-server-ts 'cd ~/homelab/docker/repo-archiver && docker build -t bucket-hub-repo-archiver:1 .'
```
