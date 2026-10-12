# AP-3.1 handoff: deploy and acceptance (Cursor prompt)

Paste everything below the line into Cursor.

---

You are the **deploy and ops agent** for Bucket-HUB on `llm-swarm-router`, app root `homelab/bucket-hub/`. The PM wrote AP-3.1 and committed it locally on branch **`pm/ap-3.1`** (the PM cannot push). Your job: push it, open the PR, deploy it, run the acceptance script, record evidence. Do not change application code; if something fails, report it with logs. British English. No secrets in files, commits, logs or replies.

## READ FIRST (in order)

1. `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`
2. `homelab/bucket-hub/docs/testing/AP-3.1-test-report.md`
3. `homelab/bucket-hub/docs/REPO-ARCHIVE.md` (new "Claim lanes" and "README.md" sections; image `:2`)
4. `homelab/bucket-hub/scripts/smoke-ap31-lanes.sh`
5. `homelab/bucket-hub/scripts/deploy-manifest.txt` (`docker/repo-archiver/*` now in `[worker]`)

## What AP-3.1 changes

- **Lane-aware claim:** `POST /api/jobs/claim` takes optional `{"lane": "aria2"|"video"|"repo"|"repo_meta"|…}`; the worker's four dispatch loops each pass their lane, so a queued repo job can no longer be claimed and bounced by the aria2 loop. No body keeps the old behaviour (old worker + new Pi is safe).
- **TNAS back-off:** a "TNAS offline, will retry" defer sets `not_before` (default 120 s, `HUB_REPO_DEFER_S`); every claim skips the job until then.
- **Pi keeps worker fields:** `JobUpdate` now accepts `error_display`, `resolved`, `not_before` (all were silently dropped), so the defer message shows in the UI.
- **Token out of argv:** `gluetun_http_json` sends `Authorization` over stdin (`docker run -i … curl -H @-`).
- **README.md:** archiver image `:2` copies `README`, `README.md`, `.rst`, `.txt`, … (case-insensitive) as `README.md`; worker falls back to `GET /repos/{o}/{r}/readme` if none was written.
- **Deploy path:** the archiver build context ships with the worker manifest and is parity-checked.

## 1. Push and PR

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
git fetch offline-intelligence
git switch pm/ap-3.1
git rebase offline-intelligence/main      # PR #4 merged there; resolve only doc conflicts, stop on code conflicts
cd homelab/bucket-hub && PYTHONPATH=. uv run --with pytest pytest tests/ -q   # expect 177 passed
cd ../.. && git push -u offline-intelligence pm/ap-3.1
```

Open a **draft** PR `pm/ap-3.1` → `main` titled "AP-3.1: lane-aware claim, TNAS back-off, README fix". Body: Before/After from "What AP-3.1 changes" above, and a link to the test report.

## 2. Deploy (order matters: Pi first, then worker)

1. Parity before: `./scripts/verify-deploy-parity.sh pi` and `./scripts/verify-deploy-parity.sh worker` (expect mismatches only on AP-3.1 files).
2. **Pi:** rsync the `[pi]` manifest set to `~/homelab/hub-form/`, restart `hub-form`. Confirm `GET http://100.85.42.0:3000/api/repo-lane` returns 200 and the worker log keeps claiming normally (old worker against new Pi is supported).
3. **Worker:** rsync the `[worker]` manifest set to `~/homelab/scripts/` (now includes `docker/repo-archiver/`), then:
   ```bash
   ssh ai-server-ts 'cd ~/homelab/scripts/docker/repo-archiver && docker build -t bucket-hub-repo-archiver:2 .'
   ```
4. **Finn edits** `~/homelab/scripts/hub-worker.env`: `REPO_ARCHIVER_IMAGE=bucket-hub-repo-archiver:2`. Confirm without printing values: `ssh ai-server-ts "grep -c '^REPO_ARCHIVER_IMAGE=bucket-hub-repo-archiver:2$' ~/homelab/scripts/hub-worker.env"` → `1`.
5. Restart `hub-worker`; parity after on both hosts (exit 0). Log the last 30 worker lines filtered for `claimed|heartbeat failed|loop error|hub http`.

## 3. Acceptance: §T6 step 2 (adversarial order)

Pick a small, well-seeded legal torrent and the Expansion HDD torrent inbox ids (`GET http://100.85.42.0:3000/api/library`). Make sure no repo job is running, then:

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router/homelab/bucket-hub
TORRENT_URL='<magnet or .torrent URL>' DRIVE_ID='<id>' FOLDER_ID='<torrents inbox id>' \
  ./scripts/smoke-ap31-lanes.sh 2>&1 | tee /tmp/ap31-smoke.log
```

It queues a long clone (`git/git`) to hold the repo slot, then two repo jobs **ahead** of the torrent, then the torrent. **Pass** = script ends with both `PASS` lines (torrent claimed ≤ 60 s and bytes rise while the clone runs; Hello-World gets a non-empty `readme_excerpt`). If the torrent errors at once, the URL is bad: pick another and re-run; that is not an AP-3.1 failure.

Then:
- `ssh ai-server-ts 'ls -la /mnt/tnas/repo-archive/github-daily/*/octocat__Hello-World/'` shows `README.md`, `repo.git/`, both sidecars, no `.partial-*`.
- Token check: while any `github_repo` job is in `checking`, run `ssh ai-server-ts "ps -eo args | grep -c 'Authorization: Bearer' "` → `1` (only the grep itself).

## DOCUMENTS TO UPDATE

- `homelab/bucket-hub/docs/testing/AP-3.1-test-report.md`: fill the "Manual acceptance" table; paste the script's status table.
- `homelab/bucket-hub/docs/testing/AP-3-test-report.md`: mark §T6 step 2 and step 3 (README) **pass**, linking the AP-3.1 report.
- `CHANGELOG.md`: AP-3.1 entry (lane claim, back-off, README, token, deploy path, image `:2`).
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`: tick AP-3.1 sub-items and the §T6 step 2 box; one session log row. Do not change decisions.
- Handoff `homelab/bucket-hub/docs/pm/2026-10/handoffs/PM-PASTE-2026-10-12-ap31.md` (READ FIRST, CONTEXT UPDATE, Request) for Finn to paste to the PM.

## Finish

Reply to Finn with: PR link, deploy steps done (one line each), smoke PASS/FAIL with the table, anything needing Finn, and the handoff path. If the smoke passes, AP-3 is **done** and AP-4 is unblocked.
