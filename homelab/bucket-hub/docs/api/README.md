# Bucket-HUB HTTP API (subset)

Full surface lives in `app.py`. This document lists repo-lane endpoints added in AP-3 and later packets.

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

## `POST /api/jobs/{id}/gate-check` (AP-4.1)

"Check now" for a `huggingface_repo` job waiting on a licence: clears `not_before` so the next worker claim re-probes access.

- **200:** `{ "ok": true, "job": { ..., "gate": { "state": "awaiting_licence", "gated": "auto", "url": "https://huggingface.co/<id>", "since": "…", "checks": 3, "next_check": "…" } } }`
- **404:** job missing, or not `queued` with a `gate`.

Job field `gate` is written by the worker via `PATCH /api/jobs/{id}` (`"gate": null` clears it); `POST /api/jobs/{id}/retry` drops it.

```bash
curl -s -X POST http://100.85.42.0:3000/api/jobs/<id>/gate-check | jq '{ok, gate: .job.gate}'
```


## `GET /api/presets` (AP-UX-1)

Every download preset resolved against the current library. No job is created.

```json
{
  "segments": [{"id": "tv", "label": "TV & film"}, {"id": "repo", "label": "Repo archive"},
               {"id": "website", "label": "Websites"}, {"id": "other", "label": "Other"}],
  "presets": [
    {"id": "tv", "preset": "tv", "segment": "tv", "label": "TV episode or season", "kinds": ["magnet", "http"],
     "available": true, "reason": "", "fallback_used": false,
     "destination": {"drive_id": "ext_movies", "folder_id": "torrents", "folder_name": "torrents",
                     "path": "/mnt/external/movies/torrents", "label": "Expansion HDD › torrents"},
     "saves_to": "Expansion HDD › torrents (Sonarr files it under TV)"}
  ]
}
```

Archive-root presets (`github_repo`, `hf_repo`) have `destination: {"archive_root": "…", "subdir": "github-daily"}`. An unavailable preset has `available: false`, `destination: null` and a `reason` such as "Expansion HDD is not mounted on the worker".

## `POST /api/presets/resolve` (AP-UX-1)

Body `{url, preset?, torrent_category?}` → the preset row above plus `kind` (job kind it would run) and `detected_kind`. Without `preset` the server suggests one from the URL.

```bash
curl -s -X POST http://100.85.42.0:3000/api/presets/resolve -H 'Content-Type: application/json' \
  -d '{"url":"https://github.com/octocat/Hello-World"}' | jq '{preset, saves_to}'
```

## `POST /api/jobs` destination fields (AP-UX-1)

| Field | Meaning |
|-------|---------|
| `preset` | Preset id. Without `manual_path` the preset decides drive/folder; stray `drive_id`/`folder_id` are ignored |
| `manual_path` | `true` → use `drive_id`/`folder_id` as given |
| neither | `drive_id` + `folder_id` without a preset = old client (`destination_source: "legacy"`); nothing at all = preset suggested from the URL |

Stored on the job: `preset`, `segment`, `destination_source` (`preset` / `manual` / `legacy`), `saves_to`. Unavailable preset → **503** with the reason; a link that does not fit the preset (e.g. YouTube with `tv`) → **400**. `GET /api/jobs?segment=tv|repo|website|other` filters; jobs from before AP-UX-1 get a segment derived from their kind.
