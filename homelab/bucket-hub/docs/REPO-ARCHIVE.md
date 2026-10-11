# Repo archive (GitHub / HF)

Operator notes for the TNAS repo lane (AP-3+).

## Layout

- Root: `HUB_REPO_ARCHIVE_ROOT` (default `/mnt/tnas/repo-archive`)
- GitHub dailies: `github-daily/YYYY-MM-DD/owner__repo/`
- Work in progress: `.partial-<job_id>/` inside the dated folder (atomic rename on success)

## Worker env (ai-server)

| Variable | Purpose |
|----------|---------|
| `HUB_REPO_ARCHIVE_ROOT` | TNAS mount path |
| `HUB_SLOT_REPO` | Concurrent repo downloads (default `1`) |
| `HUB_GITHUB_TOKEN` | GitHub API + clone auth via Gluetun |
| `REPO_ARCHIVER_IMAGE` | e.g. `bucket-hub-repo-archiver:1` |

Build image:

```bash
cd homelab/bucket-hub
docker build -t bucket-hub-repo-archiver:1 docker/repo-archiver
```

## Deploy

Rsync worker + Pi manifest sets; restart `hub-worker` and `hub-form`; run `scripts/verify-deploy-parity.sh` on both hosts.
