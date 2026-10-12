# Download index — one record per download, for people and machines

**Since:** AP-5a.1 (2026-10-12); catalogue on ai-server since AP-5a.2. **Spec:** `docs/pm/2026-10/AP-5-index-architecture-v2.md` § Per-download record.

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

Deletes made outside the Hub (Finder, Sonarr upgrades) are picked up by the catalogue scan (below), not here.

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

## Catalogue on ai-server (AP-5a.2): search every drive

`hub_index.py` (user unit `hub-index.service`, port 3031) keeps a SQLite FTS5 cache at `~/homelab/data/hub-index/catalog.sqlite` on ai-server's system SSD. It is **derived**: the journal and the files are the truth, and deleting the file loses nothing.

| What it holds | From |
|---------------|------|
| One **item** per Hub record (`item_id` = `entry_id`) | the Pi journal, tailed every 30 s via `/api/index/export?since=` |
| One **item** per folder found on a drive with no Hub record (`fs:<root>:<path>`): `tv/<Show>`, `movies/<Film>`, `torrents/<release>`, `repo-archive/github-daily/<day>/<repo>`, else the parent folder | the scans |
| One **file** row per file (`.git` internals, `@eaDir`, `#recycle`, `.cache`, `.partial-*`, `.hub-*` sidecars skipped; a bare `repo.git` is one entry) | the scans |

Roots: `tnas` (`/mnt/tnas`), `media` (`/mnt/media`), and `ext_<name>` for every drive under `/mnt/external` (`ext_movies` = Expansion HDD). Override with `HUB_INDEX_ROOTS=id=/path,…` in `hub-worker.env`.

**When it updates**

| When | What |
|------|------|
| Every 30 s | journal tail (new downloads, notes, Hub deletes) |
| A job finishes | the worker POSTs `/ingest {job_id}`: journal tail + scan of that job's folder only |
| Nightly, overnight step **Rebuild download index** (after the queue drain, before ai-server sleeps) | incremental scan of every mounted root, purge, push the item snapshot to the Pi (`$JOBS_DIR/index-snapshot.jsonl.gz`) |
| First start | a full rebuild in the background |

**Statuses:** `present`; `offline` (the drive is not mounted, e.g. TNAS asleep: rows are kept); `missing` (a full scan of a mounted drive did not find it: deleted outside the Hub; purged after 30 days); `deleted` (deleted through the Hub; hidden unless `status=deleted`; purged after 30 days); `recorded` (a Hub record with no files of its own, e.g. a TV torrent Sonarr has moved). An empty listing of a drive that had more than 100 files is treated as a mount problem (`offline`), never as a mass delete.

**Safety:** read-only (list and stat only); every walk runs in a child process with a time limit, so a stale mount cannot hang the service; nothing it returns may contain a secret (`secret_scan` on output).

```bash
ssh ai-server-ts 'curl -s 127.0.0.1:3031/health | jq "{items, files, last_rebuild, roots: [.roots[] | {root_id, mounted, last_full_scan}]}"'
ssh ai-server-ts 'curl -s "127.0.0.1:3031/search?q=office&kind=tv" | jq ".items[] | {title, where, status, file_count}"'
ssh ai-server-ts 'curl -s "127.0.0.1:3031/search?q=S03E01&scope=files" | jq ".files[] | {where, item: .item.title}"'
ssh ai-server-ts 'cd ~/homelab/scripts && set -a && . ./hub-worker.env && set +a && python3 hub_index.py rebuild'   # what the nightly step runs
ssh ai-server-ts 'systemctl --user stop hub-index && cd ~/homelab/scripts && set -a && . ./hub-worker.env && set +a && python3 hub_index.py rebuild --local --fresh; systemctl --user start hub-index'   # recovery: rebuild from scratch
```

`/search` parameters: `q` (every term must match, prefix match per term), `kind`, `root`, `status`, `scope=items|files|all`, `limit` (≤ 200), `offset`. `/item/<item_id>` returns the item, its journal record and up to 200 files. `POST /ingest` and `POST /rebuild` need the worker token. The Hub search box and the Pi fallback while ai-server sleeps come in AP-5b.

## Secrets

Every line goes through `index_writer.secret_scan`; free text (notes, README excerpts, cards) is scrubbed with `scrub_free_text` first. URLs lose credential query parameters (`redact_source_url`).
