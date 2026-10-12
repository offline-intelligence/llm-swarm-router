# OPS-ARR2: worker → Sonarr/Radarr reachability (folds OPS-ARR1)

**Owner:** PM (code), Cursor (diagnose, deploy, QC), Finn (env values).  
**Status:** built 2026-10-12 on `pm/ops-arr2`.  
**Evidence:** `handoffs/PM-PASTE-2026-10-12-sonarr-import.md`, `qc/AP-UX-1-r2.json` (`info.arr_reachable`, R0 `ConnectionResetError`).

## Problem

`hub-worker` runs on the ai-server host (systemd). Sonarr and Radarr run in Gluetun's network namespace (`network_mode: service:gluetun`), reached on ports that Gluetun publishes. On 2026-10-12, a call from the host to `127.0.0.1:8989` got `Connection reset by peer`, while the API answered from inside the container. When *The Office US S03* finished, `ensure_sonarr_series_for_job` failed. The queue said **Library import failed** (`add_failed`), and no import ran until Finn started one by hand.

OPS-ARR1 (`/ping` 000 from the worker host, found during AP-UX-1 R0) is the same fault, so it is folded in here.

Two things were wrong:

1. **No working path** from the host to the *arr API. The cause is not proven yet. The D1 probes tell the candidates apart:
   - Sonarr/Radarr still attached to a namespace that a Gluetun restart left dead;
   - `BindAddress` set to 127.0.0.1;
   - the userland proxy on 127.0.0.1 failing while the LAN IP works.
2. **One code for two failures.** "Could not reach Sonarr" and "Sonarr refused the add" both showed as `add_failed`. The scan result was never recorded. The worker also sent its Hub worker token to Sonarr/Radarr.

## Change (PM)

| Piece | What |
|-------|------|
| `arr_client.py` (new, worker) | One client for both apps. `SONARR_URL` / `RADARR_URL` over HTTP (default, unchanged). If `SONARR_VIA_DOCKER=<container>` / `RADARR_VIA_DOCKER=<container>` is set, the call becomes `docker exec -i <container> curl -K -` to `127.0.0.1:<port>` inside the container. The API key and body go on stdin, never in argv or logs. Raises `ArrUnreachable` (no answer: reset, refused, timeout, container or curl missing) or `ArrHTTPError` (the API answered 4xx/5xx). `python3 arr_client.py --check` prints one JSON line per app (`service, transport, url, ok, code, ms, version`) and exits 1 if a configured app is unreachable. |
| `hub-worker.py` | Every Sonarr/Radarr call goes through `arr_client.request`. `ensure_*` returns `api_unreachable` or `add_failed` (plus the existing `added`, `exists`, `lookup_failed`, `skipped`). An unreachable API no longer hides inside the in-library check. `notify_media_libraries_after_torrent` records `sonarr_scan` / `radarr_scan` = `requested` \| `api_unreachable` \| `failed`, and skips the scan when the add already found the API unreachable. The Hub worker token is no longer sent to *arr. |
| `job_health.py` | Agent review code `sonarr_unreachable`, separate from `sonarr_import_failed`. The playbook points at `arr_client.py --check` and `SONARR_VIA_DOCKER`. |
| `form.html` | Queue hint: **Library import failed: Sonarr not reachable** / **…: Radarr not reachable** / **…: scan refused**; the old **Library import failed** stays for `add_failed`. `glance.yml` `?v=20261012arr2`. |
| `scripts/smoke-ops-arr2.sh` (new) | D1 read-only path probes; M1 `arr_client.py --check` with `hub-worker.env` loaded. |

## `media_pipeline` values

| key | values |
|-----|--------|
| `sonarr` / `radarr` | `added`, `exists`, `lookup_failed`, `add_failed`, `api_unreachable`, `skipped` |
| `sonarr_scan` / `radarr_scan` | `requested`, `failed`, `api_unreachable` (absent on jobs from before OPS-ARR2) |
| `jellyfin_refreshed` | bool |

## Choosing the transport (Cursor reads D1; Finn sets env)

Take the first row that matches, for each app:

| D1 shows | Action |
|----------|--------|
| `host_loopback` = 200 | Keep the defaults. No env change. |
| `netns_current` = false | `docker restart sonarr radarr` (re-attach to the running Gluetun), then run D1 again |
| `host_lan` = 200 | Finn sets `SONARR_URL=http://<lan_ip>:8989` (Radarr `:7878`) |
| `in_app` = 200 and `app_has_curl` = true, and the worker user can run `docker` | Finn adds `SONARR_VIA_DOCKER=sonarr` (Radarr `RADARR_VIA_DOCKER=radarr`) |
| none | Blocker: report D1 to the PM |

Restart `hub-worker` after an env change. M1 must then pass.

## Tests

`tests/test_arr_client.py`, 15 tests:

- **A1–A7, client:** env parsing; classification; HTTP 200 / 401 / refused; docker argv carries no key; docker error codes; `--check` output and exit code; the curl config run through real curl.
- **W1–W3, worker:** unreachable add → `api_unreachable`; unreachable skips the scan; refused scan → `failed`; accepted scan → `requested`.
- **H1, health:** `sonarr_unreachable` vs `sonarr_import_failed`.

## Out of scope (backlog)

- A **Retry library import** button (re-run ensure + scan for a finished job).
- An ops guard that restarts *arr after a Gluetun restart.
