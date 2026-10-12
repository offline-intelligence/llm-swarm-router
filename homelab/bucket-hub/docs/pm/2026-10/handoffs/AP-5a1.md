# AP-5a.1 round 1: per-download record (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). You do not edit application code, tests, `Caddyfile`, `glance.yml` or `scripts/smoke-*.sh`. Failing check → finding with `repro`, stop dependent steps, continue with independent ones. Never print a token or API key.

WHAT THIS IS: Finn's "per-download indexing for both user and machine, updated on delete and nightly". PM split AP-5a in two. **AP-5a.1 (this round)** is the record itself: the Pi journal API (search, card, note, export with a cursor, sources, entries), delete tombstones, and `ABOUT-THIS-DOWNLOAD.md` beside GitHub/HF archives. **AP-5a.2 (next)** is the ai-server catalogue that scans every drive, picks up deletes made outside the Hub, and rebuilds after the nightly sync.

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (`bucket-hub-qc/v1`).

OUTPUT: `homelab/bucket-hub/docs/pm/2026-10/qc/AP-5a1-r1.json`, committed on `pm/ap-5a1`, pushed. Reply = that JSON in one ```json block, then at most 5 lines.

## READ FIRST

1. `homelab/bucket-hub/docs/DOWNLOAD-INDEX.md`
2. `homelab/bucket-hub/docs/testing/AP-5a1-test-report.md` ("Behaviour changes")
3. `homelab/bucket-hub/docs/pm/2026-10/AP-5-index-architecture-v2.md` § Per-download record

## INPUT

| Key | Value |
|-----|-------|
| branch | `pm/ap-5a1` (local, on top of `99db36c`) |
| PR | draft, base `main`. If `pm/qc-close-2026-10-12` is not merged yet, merge that PR first (its QC passed), then rebase `pm/ap-5a1` onto `main` (conflicts → finding, do not resolve) |
| deploy | `[pi]` (app.py, `download_record.py`, back-fill script) + `[worker]` (`download_record.py`, `repo_archive_github.py`). No gateway change |

## S0 git + unit

First install the HF client in the venv you test with so no test is skipped: `uv pip install huggingface_hub` (or `python3 -m pip install huggingface_hub`).

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
git checkout pm/ap-5a1 && git log --oneline -3
cd homelab/bucket-hub && PYTHONPATH=. python3 -m pytest -q 2>&1 | tail -1
```

| id | expected |
|----|----------|
| `unit.pytest` | `301 passed`, 0 skipped, 0 failed |
| `git.push` / `git.pr` | pushed; draft PR url |

## S1 deploy

Precondition: no repo job running on the worker (`active_repo` = 0). Pi: rsync `[pi]` to `stackrise-pi:homelab/hub-form/` (no leading `~` in the remote path; r2 deviation), `systemctl --user restart hub-form.service`. Worker: rsync `[worker]`, restart `hub-worker`.

| id | expected |
|----|----------|
| `deploy.pi_parity` / `deploy.worker_parity` | exit 0 each |
| `deploy.pi_app_reloaded` | process start later than `app.py` mtime |
| `deploy.worker_service` | active, 0 errors in the first 2 min |
| `deploy.index_endpoint` | `curl -s -o /dev/null -w '%{http_code}' http://100.85.42.0:3000/api/index/search?q=` = `200` |

## S2 smoke

```bash
QC_OUT=/tmp/ap5a1-qc.json ./scripts/smoke-ap5a1-index.sh 2>&1 | tee /tmp/ap5a1-smoke.log
```

Checks `smoke.x1_export` … `smoke.x7_backfill_dry_run` = pass. `info.backfill_counts` = the X7 value (PM reviews it before any real back-fill; **do not run without `--dry-run`**). Dismiss the X6 job (`JOBS` line) afterwards. If X2 finds no Hello-World record, record it and continue (it only exists if an AP-3 smoke ran against this Hub's journal).

## S3 Finn check (optional, one line)

Ask Finn to open `http://100.85.42.0:3000/api/index/search?q=tiny-random-gpt2` and then the `/card` URL of the first `entry_id`, and say whether the card reads well. `ui.card` = his words, or `skip` if he does not answer this round.

## overall

`pass` only if every non-`info`, non-`ui` check is `pass`.

## DOCUMENTS TO UPDATE (only these)

- `qc/AP-5a1-r1.json` (new).
- `docs/testing/AP-5a1-test-report.md`: "Manual acceptance".
- `docs/agent-context/PROJECT-STATE.md`: one session-log row citing the file; tick the AP-5a.1 backlog line if `pass`.
- `TODO.md`: tick the AP-5a.1 line if `pass`.
- `CHANGELOG.md`: "Deployed 2026-10-12, QC r1 <overall>" under AP-5a.1.
- If `pass`: `gh pr ready <n>`; merge only when this handoff's next round says so.
