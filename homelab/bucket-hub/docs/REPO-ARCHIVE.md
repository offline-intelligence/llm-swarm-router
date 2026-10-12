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
| `REPO_ARCHIVER_IMAGE` | `bucket-hub-repo-archiver:4` from AP-4 (adds `hf_snapshot`, pinned `huggingface_hub==0.26.2`). `:3` = GitHub heads+tags only; `:2` pulled `refs/pull/*`; `:1` only read `HEAD:README.md` |
| `HF_TOKEN` | Hugging Face read token, same account Finn uses in the browser. Optional for public repos, **required for any gated model** (without it gated jobs wait as `needs_token`). Sent to the HF API over stdin and to the archiver via the env file, never argv |
| `HF_GATE_RECHECK_S` | Seconds between access re-checks for a job waiting on a licence (default `600`) |
| `HF_GATE_MAX_WAIT_H` | Hours a gated job waits for the licence before it errors (default `168`) |
| `HUB_REPO_DEFER_S` | Seconds a job waits before re-claim after "TNAS offline, will retry" (default `120`) |
| `HUB_REPO_RECHECK_S` | Seconds the worker waits to re-check the archive mount before it defers a job (default `5`) |

CIFS mount: `~/homelab/scripts/mount-tnas-docker.sh` reads `TNAS_HOST`, `TNAS_SHARE`, `TNAS_USER`, `TNAS_PASSWORD` from `~/homelab/.env`. **Current TNAS LAN host:** `192.168.50.187` (`TNAS_HOST` on ai-server). **DHCP reservation:** done 2026-10-12 (ASUS RT-AX57, `tnas` → `.187`).

Build image:

```bash
cd homelab/bucket-hub
docker build -t bucket-hub-repo-archiver:4 docker/repo-archiver
```

## Claim lanes (AP-3.1)

Each worker dispatch loop claims with `POST /api/jobs/claim {"lane": "aria2" | "video" | "repo" | "repo_meta"}`, so a loop never claims a job it would have to put back. No body (or `{}`) keeps the old any-lane claim. A job with `not_before` in the future is skipped by every claim.

## What is archived

`repo.git` is a bare repo holding **branches and tags only** (`+refs/heads/*`, `+refs/tags/*`), with `HEAD` set to the remote default branch. GitHub's `refs/pull/*` are not fetched: on popular repos they carry thousands of fork commits that the API `size` does not count (AP-3.1 QC r2: Spoon-Knife blew a 64 MB cap). To refresh an archive by hand: `git --git-dir repo.git fetch --prune origin`.

## TNAS readiness

Before a repo job is deferred, the worker re-checks the mount once after `HUB_REPO_RECHECK_S`, and first clears a "stale" mark if the mount answers a `stat` again. The deferred job's `progress.note` carries the reason, e.g. `TNAS offline, will retry (NAS is not mounted)`.

## Hugging Face (`huggingface_repo`, AP-4)

Queue with `POST /api/jobs` `{"kind": "huggingface_repo", "url": "https://huggingface.co/<org>/<name>", "options": {…}}` or paste a huggingface.co URL with Type = Auto. No drive or folder is needed; the worker writes to `huggingface-daily/<day>/<models|datasets>__<org>__<name>/` with `snapshot/` (real files, not LFS pointers), `README.md` (the card) and both sidecars.

| Option | Default | Meaning |
|--------|---------|---------|
| `repo_type` | `model` (a `/datasets/` URL sets `dataset`) | Spaces are rejected |
| `revision` | `main` | resolved to the commit `sha` before download, so the size check and the snapshot match |
| `max_size_mb` | `20480` | pre-check on the API's per-file sizes after patterns; over the cap = `done` "Skipped: …" + `skipped_too_large` index entry |
| `prefer_safetensors` | `true` | if any `*.safetensors` exists, `*.bin`, `*.pt`, `*.pth`, `*.ckpt`, `*.h5`, `*.msgpack` are ignored |
| `allow_patterns` / `ignore_patterns` | none | fnmatch patterns like `huggingface_hub`; an explicit allow list wins over `prefer_safetensors`, and `README.md` is always kept |
| `refresh` | `false` | download again even if archived |

Errors read: "Repository not found or private", "Hugging Face Spaces are not archived (models and datasets only)". Gated models do not error (next section).

### Gated models (AP-4.1, one click)

Hugging Face has no API for a user to accept a licence (the `huggingface_hub` access-request calls are for repo owners), so the Hub does everything around the click:

1. After metadata, a gated repo (`gated: "auto"` or `"manual"`) is probed with `HEAD https://huggingface.co/<id>/resolve/<sha>/<README.md or smallest file>` (token over stdin, no redirects).
2. 401/403 → the job goes back to `queued` with `gate = {state: "awaiting_licence", gated, url, since, checks, next_check}` and `not_before` = now + `HF_GATE_RECHECK_S`. No token → `gate.state = "needs_token"`. Nothing is downloaded.
3. The Hub queue shows **Licence needed**, an **Accept licence** button (the model page) and **Check now**; a "Waiting for a licence (N)" bar lists every waiting job.
4. Finn accepts once on huggingface.co. The next re-check (or Check now, `POST /api/jobs/{id}/gate-check`) finds access and the normal download runs. Acceptance covers every later revision.
5. After `HF_GATE_MAX_WAIT_H` the job errors "Licence not accepted within 168 h"; Retry starts a fresh wait.

`manual` repos wait for the model owner's approval; the card says so. Index entries record `licence_accepted_by: "user"` and `gate_wait_s`.

The Hub form's "Hugging Face repo (TNAS archive)" type and HF search results queue `huggingface_repo`; "Select files" still queues the legacy `hf` kind into the chosen drive.

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
ssh ai-server-ts 'cd ~/homelab/scripts/docker/repo-archiver && docker build -t bucket-hub-repo-archiver:4 .'
```
