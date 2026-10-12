# AP-4.1 test report — Hugging Face gated repos (one-click licence)

**Branch:** `pm/ap-4.1` (stacked on `pm/ap-4`). **Spec:** `docs/pm/2026-10/AP-4.1-hf-gated-access.md`. **Written by:** PM (2026-10-12).

## What changed

| File | Change |
|------|--------|
| `repo_archive_hf.py` | After metadata, a gated repo is probed (`HEAD …/resolve/<sha>/<README.md or smallest file>`, no redirects). 401/403 → job back to `queued` with `gate` + `not_before`; no `HF_TOKEN` → `gate.state = needs_token`. Re-claims re-probe only. Wait expires after `HF_GATE_MAX_WAIT_H` (168). A gated error mid-download parks the job again. Probe errors let the download decide. Final PATCH clears `gate`; index records `licence_accepted_by` / `gate_wait_s` |
| `hub-worker.py` | `gluetun_http_status()` (curl `-I`, `-w %{http_code}`, token over stdin); wired as `probe_access`; `update_job(gate=None)` sends an explicit null |
| `app.py` | `JobUpdate.gate` (null clears); `POST /api/jobs/{id}/gate-check` ("Check now": clears `not_before`, 404 unless queued with a gate); `retry` drops `gate` and `not_before` |
| `index_writer.py` | `licence_accepted_by`, `gate_wait_s` on `huggingface_repo` entries |
| `form.html` | `gateBlock()` on job rows and queue detail (Accept licence link + Check now); "Waiting for a licence (N)" bar above the queue; status pill "Licence needed" / "Needs HF token" |
| `glance.yml` | iframe `?v=20261012ap41` |
| `scripts/smoke-ap41-gate.sh` | two-phase live acceptance (7 checks) |

No new files for the deploy manifest; no archiver image change (`:4` stays).

## Unit tests (PM)

`PYTHONPATH=. pytest tests/ -q` → **239 passed** (217 from AP-4 + 19 in `tests/test_repo_archive_hf_gate.py` + 3 new `test_form_escaping` cases).

| Spec id | Test |
|---------|------|
| G1 | `test_g1_not_gated_skips_probe` |
| G2 | `test_g2_gated_without_token_waits_needs_token` |
| G3 | `test_g3_gated_probe_403_awaits_licence`, `test_g3_manual_gate_note` |
| G4 | `test_g4_access_granted_downloads_and_records`, `test_g4_counts_checks_across_claims` |
| G5 | `test_g5_wait_expires`, `test_g5_wait_window_from_env` |
| G6 | `test_g6_gated_error_mid_download_waits_again`, `test_g6_probe_error_lets_download_decide` |
| G7 | `test_g7_patch_stores_and_clears_gate`, `test_g7_gate_check_clears_not_before`, `test_g7_gate_check_404_without_gate`, `test_g7_retry_starts_a_fresh_wait` |
| G8 | `test_g8_probe_is_head_without_redirects_token_over_stdin`, `test_g8_worker_wires_probe`, `test_g8_update_job_sends_gate_null` |
| G9 | token absent from argv (inside the G8 probe test) |
| UI | `test_innerhtml_interpolations_escaped[gateBlock|renderLicenceBar|licenceBarRow]` |

## Smoke script dry run (PM)

`scripts/smoke-ap41-gate.sh` was run against the real `app.py` (uvicorn, temp `JOBS_DIR`) with a local worker loop that calls the real `run_huggingface_repo_job`, with a fake metadata fetcher, a fake access probe (403 until an "accepted" flag file exists) and `RecordingRepoRunner`:

- PHASE=1: `gate_precheck`, `gate_check_404`, `g_waiting`, `g_waiting_stable` → **4/4 pass**
- (flag file created = "Finn accepts")
- PHASE=2: `g_check_now`, `g_done`, `g_index` → **3/3 pass** (`licence_accepted_by: user`, `gate_wait_s: 72`)

## Manual acceptance (Cursor fills in)

| Check | Result | Evidence |
|-------|--------|----------|
| deploy parity pi / worker | | |
| Pi app reloaded (gate-check endpoint live) | | |
| `smoke.gate_*` / `smoke.g_waiting*` (phase 1) | | |
| Finn: UI shows "Licence needed" + Accept licence + waiting bar | | |
| `smoke.g_check_now` / `g_done` / `g_index` (phase 2) | | |
| real weights on TNAS, no partials | | |
| `HF_TOKEN` not in `ps` during phase 2 | | |

## Not covered live

- `needs_token` (L4): unit test G2 only; a live run needs an env edit and restart mid-QC.
- `gated: "manual"` repos: unit test only; the owner's approval time is outside our control.
