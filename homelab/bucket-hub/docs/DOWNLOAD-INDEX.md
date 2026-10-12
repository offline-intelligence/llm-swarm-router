# Download index — one record per download, for people and machines

**Since:** AP-5a.1 (2026-10-12). **Spec:** `docs/pm/2026-10/AP-5-index-architecture-v2.md` § Per-download record.

## Where the record lives

| What | Where | Who writes it |
|------|-------|---------------|
| Journal (truth for every kind) | Pi `$JOBS_DIR/download-index.jsonl` | `app.py` when a job finishes; note edits; delete tombstones |
| Repo journal | TNAS `repo-archive/download-index.jsonl` | worker after a repo archive finishes |
| Machine record beside the files | `.hub-provenance-<job>.json` (GitHub, Hugging Face) | worker |
| Person record beside the files | `ABOUT-THIS-DOWNLOAD.md` (GitHub, Hugging Face) | worker |

TV and film torrents get nothing beside their files: Sonarr and Radarr move them out of `torrents/`, so a sidecar would be left behind. Their record is the journal entry (`segment: "tv"`).

The journal is append-only. Three kinds of line:

| Line | Meaning |
|------|---------|
| an entry (schema v1, `index_writer.build_entry`) | a finished or failed download; last line wins per `entry_id`; carries `segment`, `preset`, `saves_to` from AP-UX-1 |
| `{"event": "note", "entry_id", "user_note"}` | "Why I kept this" edit |
| `{"event": "deleted", "entry_id", "paths", "by", "at"}` | the files were deleted through the Hub (Storage delete, cancel + purge); the record stays with `status: "deleted"` |

Deletes made outside the Hub (Finder, Sonarr upgrades) are picked up by the catalogue scan in AP-5a.2, not here.

## API (Pi, `http://100.85.42.0:3000`)

```bash
curl -s 'http://100.85.42.0:3000/api/index/search?q=llama' | jq '.items[] | {entry_id, title, status, segment}'
curl -s 'http://100.85.42.0:3000/api/index/search?q=llama&status=deleted' | jq .total
curl -s "http://100.85.42.0:3000/api/index/<entry_id>/card"        # Markdown: What / Where / Why / When
curl -s -X PATCH "http://100.85.42.0:3000/api/index/<entry_id>" -H 'Content-Type: application/json' -d '{"user_note":"Base model for the router"}'
curl -s -D - 'http://100.85.42.0:3000/api/index/export?since=0' | head   # JSONL; X-Index-Cursor header
curl -s 'http://100.85.42.0:3000/api/index/sources?kind=github_repo' | jq .count
```

For a machine (or the AP-5a.2 catalogue) the feed is `GET /api/index/export?since=<cursor>`: keep the `X-Index-Cursor` header from the last call and pass it back; you get every record that changed since, already merged (notes and tombstones applied). `POST /api/index/entries` (worker token) appends records, used by rebuilds.

Search is substring, every term must match, weighted: title/name 3, tags/topics 2, description/note/context 1.5, README excerpt/path 1. Deleted and failed records are hidden unless `status=deleted` / `status=failed`.

## Back-fill old jobs

```bash
ssh stackrise-pi 'cd ~/homelab/hub-form && python3 scripts/rebuild-download-index.py --from-jobs ~/homelab/data/hub-jobs --dry-run'
```

Prints counts by kind. Without `--dry-run` it appends one minimal entry per finished download job that has no record yet (idempotent, append-only). PM reviews the dry-run counts first.

Not downloads, never indexed (`download_record.NOT_DOWNLOADS`): `storage_delete`, `sync`, `storage_scan`, `github_stars_sync`, `huggingface_likes_sync`, `minecraft`.

## Secrets

Every line goes through `index_writer.secret_scan`; free text (notes, README excerpts, cards) is scrubbed with `scrub_free_text` first. URLs lose credential query parameters (`redact_source_url`).
