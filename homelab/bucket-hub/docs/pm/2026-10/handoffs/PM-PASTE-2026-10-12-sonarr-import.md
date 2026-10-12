# PM paste — Sonarr import from host `hub-worker` (2026-10-12)

**From:** Cursor integrator (Finn ops session)  
**Status:** Workaround applied; **PM fix wanted** (not blocking AP-5a.1 merge)  
**User impact:** Hub queue shows **torrents · Library import failed** after a successful aria2 download; files sit in `torrents/` until manual Sonarr scan.

## Symptom

- Job: *The Office US S03* magnet (`36980247…`), aria2 completed ~9 GB under Expansion HDD.
- Hub UI: **Library import failed** (`media_pipeline.sonarr` → `add_failed` in `form.html` mapping).
- Jellyfin: no Season 3 until import runs.

## Root cause (verified on ai-server)

| Layer | Finding |
|-------|---------|
| **Worker** | `hub-worker` runs on the **host** (systemd), not inside Gluetun. |
| **Sonarr** | Container uses `network_mode: container:<gluetun>`. API is healthy **inside** the namespace. |
| **Config** | `~/homelab/scripts/hub-worker.env` has `SONARR_URL=http://127.0.0.1:8989` (same for Radarr `:7878`). |
| **Host curl** | `curl http://127.0.0.1:8989/ping` → **connection reset by peer** (HTTP 000). |
| **Worker logs** | `sonarr ensure series failed: [Errno 104] Connection reset by peer` at torrent complete time. |
| **Inside Sonarr** | `docker exec sonarr wget …/api/v3/system/status` with API key → **200**. |

Docs that assume host `127.0.0.1:8989` works are wrong for this compose layout (already noted in AP-UX-1 r2 `info.arr_reachable` / R0 `ConnectionResetError`).

**Not the issue:** missing files, wrong torrent path, or Jackett seed counts. Download was complete before import was attempted.

## Ops workaround (2026-10-12, Finn confirmed playback OK)

```bash
# On ai-server (API key from hub-worker.env — never log the key)
set -a; . ~/homelab/scripts/hub-worker.env; set +a
SCAN='/data/torrents/The.Office.US.S03.1080p.BluRay.x265-RARBG'
docker exec sonarr wget -qO- \
  --header="X-Api-Key: $SONARR_API_KEY" \
  --header='Content-Type: application/json' \
  --post-data="{\"name\":\"DownloadedEpisodesScan\",\"path\":\"$SCAN\"}" \
  'http://127.0.0.1:8989/api/v3/command'
curl -sS -X POST 'http://127.0.0.1:8096/Library/Refresh' \
  -H "X-MediaBrowser-Token: $JELLYFIN_API_KEY"
```

Result: **22 files** under `/mnt/external/movies/tv/The Office (US)/Season 3/`; Jellyfin play confirmed.

## PM directions (pick one or propose better)

1. **Worker-side HTTP client** — resolve Sonarr/Radarr via a supported URL from the host (e.g. small local forwarder, or documented bridge IP if Gluetun publish is fixed upstream).
2. **Worker-side `docker exec` helper** — optional env `SONARR_VIA_DOCKER=sonarr` so `ensure_sonarr_series_for_job` / `DownloadedEpisodesScan` use in-container `127.0.0.1` without exposing keys in logs.
3. **Health / pipeline** — if Sonarr POST fails, set `media_pipeline.sonarr` to a distinct code (e.g. `api_unreachable`) vs `add_failed`; surface in queue copy and `JOB-HEALTH-AND-AGENT-REVIEW.md`.
4. **Smoke** — extend media pipeline smoke or worker doctor: host must reach Sonarr API the same way the worker does after torrent complete.

## References

- `hub-worker.py`: `ensure_sonarr_series_for_job`, `notify_media_libraries_after_torrent`
- `docs/MEDIA-JELLYFIN-PIPELINE.md`, `docs/agent-context/08-TV-AND-MEDIA-PIPELINE.md`
- `docs/pm/2026-10/qc/AP-UX-1-r2.json` (`info.arr_reachable`, smoke R0 ConnectionResetError)
- `docs/agent-context/12-FAILURES-LIMITATIONS-TESTS.md` (Sonarr import row)

## CONTEXT UPDATE (for PROJECT-STATE)

- [ ] **OPS-ARR2** (suggested id): Host `hub-worker` cannot reach Sonarr/Radarr on published `127.0.0.1:8989` / `:7878` when *arr shares Gluetun netns → Hub **Library import failed** despite complete `torrents/` download. Manual `docker exec sonarr` scan works. PM fix on worker URL or exec bridge.
