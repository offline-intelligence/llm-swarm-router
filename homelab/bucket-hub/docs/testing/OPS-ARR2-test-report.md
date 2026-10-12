# OPS-ARR2 test report

Spec: `docs/pm/2026-10/OPS-ARR2-arr-reachability.md`. Handoff: `docs/pm/2026-10/handoffs/OPS-ARR2.md`.

## Unit (PM, 2026-10-12)

`PYTHONPATH=. python -m pytest -q` → **316 passed** (`huggingface_hub==0.26.2`; was 301). New file `tests/test_arr_client.py` (15):

| id | test | proves |
|----|------|--------|
| A1 | `test_a1_target_from_env` | defaults `127.0.0.1:8989/7878`, `*_VIA_DOCKER` → `docker:<name>`, port from URL |
| A2 | `test_a2_classify` | reset / refused / timeout → `api_unreachable`; HTTP error or bad payload → `add_failed` |
| A3 | `test_a3_http_ok_401_and_refused` | HTTP 200 parsed; 401 → `ArrHTTPError`; closed port → `ArrUnreachable`; no `X-Worker-Token` sent to *arr |
| A4 | `test_a4_docker_transport_key_on_stdin_only` | `docker exec -i sonarr curl -K -`; key only on stdin; body quotes escaped |
| A5 | `test_a5_docker_errors` (5) | curl 7, docker 125/127, status 000 → unreachable; 404 → HTTP error |
| A6 | `test_a6_check_and_cli` | `--check` rows, `not_configured`, exit 1 on unreachable, key never printed |
| A7 | `test_a7_docker_config_runs_in_real_curl` | the `-K` config (escapes, status line) works in real curl |
| W1 | `test_w1_ensure_series_reports_api_unreachable` | ensure series → `api_unreachable` |
| W2 | `test_w2_unreachable_skips_scan` | `sonarr_scan` = `api_unreachable`, no second wait on the scan |
| W3 | `test_w3_scan_refused_is_failed_and_ok_is_requested` | scan → `failed` / `requested` |
| H1 | `test_h1_job_health_codes` | `sonarr_unreachable` vs `sonarr_import_failed`; playbook names `arr_client.py --check` |

## Manual acceptance

| round | date | result | notes |
|-------|------|--------|-------|
| r1 | 2026-10-12 | **pass** | D1: host loopback/lan 000, `in_app` 200, `bind_address` * → **docker exec** transport (`SONARR_VIA_DOCKER` / `RADARR_VIA_DOCKER`). M1 ok; end-to-end scan **queued**. QC `docs/pm/2026-10/qc/OPS-ARR2-r1.json`. |
