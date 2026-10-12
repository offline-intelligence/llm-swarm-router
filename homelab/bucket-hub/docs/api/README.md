# Bucket-HUB HTTP API (subset)

Full surface lives in `app.py`. This document lists repo-lane endpoints added in AP-3.

## `GET /api/repo-lane`

Repo archive lane capacity (separate from aria2 torrent slots).

**Response (200):**

```json
{
  "archive_root": "/mnt/tnas/repo-archive",
  "slot_repo": 1,
  "active_repo": 0,
  "slot_repo_meta": 1,
  "active_repo_meta": 0,
  "kinds_repo": ["github", "github_release", "github_repo", "hf", "huggingface_repo"],
  "kinds_repo_meta": ["github_releases_sync", "github_stars_sync", "huggingface_likes_sync"]
}
```

**Example:**

```bash
curl -s http://100.85.42.0:3000/api/repo-lane | jq .
```

## `POST /api/jobs` — `kind: "github_repo"`

Enqueue a GitHub mirror archive (worker owns destination; `drive_id` / `folder_id` optional).

**Body:**

```json
{
  "kind": "github_repo",
  "url": "https://github.com/octocat/Hello-World",
  "title": "octocat/Hello-World",
  "source": "manual",
  "tags": ["github", "manual-test"],
  "options": {
    "max_size_mb": 2048,
    "refresh": false,
    "user_note": "optional"
  }
}
```

**Response (200):** `{ "ok": true, "job": { ... } }` with `options` persisted on the job.
