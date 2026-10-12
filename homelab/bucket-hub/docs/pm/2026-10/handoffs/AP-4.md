# AP-4 handoff, round 1: `huggingface_repo` integrate, deploy, QC (Cursor prompt)

Paste everything below the line into Cursor.

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). The PM wrote the code. You do not edit application code, tests or `scripts/smoke-*.sh`. On a failing check: record a finding with `repro`, stop dependent steps, continue only with independent checks, return the report. The PM fixes and sends round 2.

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (schema `bucket-hub-qc/v1`).

OUTPUT: write `homelab/bucket-hub/docs/pm/2026-10/qc/AP-4-r1.json`, commit on `pm/ap-4`, push. Reply = that JSON in one ```json block first, then at most 5 lines.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md`
2. `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md` (decisions dated 2026-10-12)
3. `homelab/bucket-hub/docs/pm/2026-10/cursor-github-hf-downloader.md` §A3, §A4 `huggingface_repo`, §A5 HF, §T3, §T6 step 6, "Action Packet: AP-4"
4. `homelab/bucket-hub/docs/REPO-ARCHIVE.md` ("Hugging Face" section)
5. `homelab/bucket-hub/docs/testing/AP-4-test-report.md`
6. `homelab/bucket-hub/docs/agent-context/05-OPERATIONS-SSH-DEPLOY.md`

## WHAT THE PM BUILT (input, do not re-litigate)

| Area | Change |
|------|--------|
| `repo_archive_hf.py` (new) | URL → `(repo_type, repo_id)`; Spaces rejected; `prefer_safetensors` and fnmatch patterns; size pre-check from API per-file sizes; card front matter; dedupe, TNAS defer, `.partial-<id>` then rename, post-check 110 %, readable gated / not-found errors; download pinned to the metadata `sha` |
| `docker/repo-archiver/*` | `hf_snapshot <repo_id> <spec-json>` mode (`snapshot_download` into `/work/snapshot`, card → `/work/README.md`); exit 3 + `error_kind` on known failures; `huggingface_hub==0.26.2` pinned. Image **`bucket-hub-repo-archiver:4`** (GitHub mode unchanged from `:3`) |
| `repo_runner.py` | `run_hf_snapshot` (12 h timeout, token only in env file); `ArchiverError(kind)` |
| `hub-worker.py` | dispatches `huggingface_repo`; HF metadata via Gluetun `GET https://huggingface.co/api/models/<id>/revision/<rev>?blobs=true` (`HF_TOKEN` over stdin) |
| `index_writer.py` | `build_hf_entry` (spec A6 HF fields), `file_summary`, `scrub_free_text` for README/card excerpts |
| `app.py`, `job_kinds.py` | huggingface.co + Auto → `huggingface_repo`; only archive-root kinds skip the drive check. **Fixes a live bug:** legacy `hf`/`github` jobs had no `destination_path` since AP-3 |
| `form.html`, `glance.yml` | Type list gains "GitHub repo (TNAS archive)" / "Hugging Face repo (TNAS archive)"; HF/GitHub search results queue the archive kinds; "Select files" stays legacy `hf`; no drive needed for archive kinds. Glance iframe `?v=20261012ap4` |
| `scripts/deploy-manifest.txt` | `repo_archive_hf.py` in `[pi]` and `[worker]` |
| `scripts/smoke-ap4-hf.sh` (new) | 7 API checks, `QC` lines + `QC_OUT` |

## INPUT

| Key | Value |
|-----|-------|
| packet / round | `AP-4` / `1` |
| branch | `pm/ap-4` (PM commits on the Mac checkout, stacked on `pm/ap-3.1` because PR #5 was not merged yet) |
| base | `offline-intelligence/main` |
| image | build **`bucket-hub-repo-archiver:4`** |
| env | `REPO_ARCHIVER_IMAGE=bucket-hub-repo-archiver:4` (Finn). `HF_TOKEN` optional: only needed for gated models; not needed for this smoke |
| smoke model | `hf-internal-testing/tiny-random-gpt2` |

## S0 pre-flight

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
gh pr view 5 --repo offline-intelligence/llm-swarm-router --json state,isDraft
```

| id | expected |
|----|----------|
| `info.pr5_state` | always `pass`; `value` = state. If `MERGED`: `git switch pm/ap-4 && git fetch offline-intelligence && git rebase offline-intelligence/main` (the AP-3.1 commits drop out). If not merged: keep `pm/ap-4` on top of `pm/ap-3.1` and open the AP-4 PR with **base `pm/ap-3.1`**, retarget to `main` after #5 merges |
| `info.legacy_hf_lfs` | always `pass`. Find one finished legacy `hf` job: `curl -s 'http://100.85.42.0:3000/api/jobs?status=done&limit=100' \| jq -c '[.jobs[] \| select(.kind=="hf") \| {id, destination_path}] \| .[:3]'`. For one of them: `ssh ai-server-ts "find '<destination_path>' -maxdepth 3 \( -name '*.safetensors' -o -name '*.bin' \) \| head -3 \| xargs -r ls -la; find '<destination_path>' -maxdepth 3 \( -name '*.safetensors' -o -name '*.bin' \) \| head -1 \| xargs -r head -c 120"`. `value` = `{sizes, starts_with_lfs_pointer: true\|false}` or `"no legacy hf job found"` |

## S1 integrate

```bash
cd homelab/bucket-hub && PYTHONPATH=. uv run --with pytest --with huggingface_hub==0.26.2 pytest tests/ -q 2>&1 | tee /tmp/ap4r1-unit.pytest.log | tail -3
cd ../.. && git push offline-intelligence pm/ap-3.1   # PM sign-off commit f4b7f05 is local only
git push -u offline-intelligence pm/ap-4
gh pr create --draft --repo offline-intelligence/llm-swarm-router --head pm/ap-4 --base <main or pm/ap-3.1 per S0> \
  --title "AP-4: huggingface_repo archive lane" --body-file homelab/bucket-hub/docs/testing/AP-4-test-report.md
```

| id | expected |
|----|----------|
| `git.rebase` | exit 0, no conflicts (or `skip` if S0 kept the stack) |
| `unit.pytest` | `217 passed`, 0 failed, 0 skipped |
| `git.push` | remote `pm/ap-4` = local `HEAD`; `value` = sha |
| `git.pr` | draft PR URL; `value` = URL |

## S2 deploy (Pi then worker)

Pi: rsync the `[pi]` manifest set to `~/homelab/hub-form/`, restart `hub-form`, reload Glance per `05-OPERATIONS-SSH-DEPLOY.md`. Worker: rsync `[worker]` to `~/homelab/scripts/`, then:

```bash
ssh ai-server-ts 'cd ~/homelab/scripts/docker/repo-archiver && docker build -t bucket-hub-repo-archiver:4 .'
ssh ai-server-ts 'docker run --rm --entrypoint python3 bucket-hub-repo-archiver:4 -c "import huggingface_hub; print(huggingface_hub.__version__)"'
```

**Finn** sets `REPO_ARCHIVER_IMAGE=bucket-hub-repo-archiver:4` in `~/homelab/scripts/hub-worker.env`. Mark `deploy.env_image` `blocked` until he confirms, then re-check. Then `ssh ai-server-ts 'systemctl --user restart hub-worker'`.

| id | expected |
|----|----------|
| `deploy.pi_parity` | `verify-deploy-parity.sh pi` exit 0 |
| `deploy.worker_parity` | `verify-deploy-parity.sh worker` exit 0 |
| `deploy.image_build` | `docker image inspect bucket-hub-repo-archiver:4 --format '{{.Id}}'` exit 0; `value` = id |
| `deploy.image_hf_version` | prints `0.26.2` |
| `deploy.env_image` | `grep -c '^REPO_ARCHIVER_IMAGE=bucket-hub-repo-archiver:4$' ~/homelab/scripts/hub-worker.env` = `1` |
| `deploy.worker_service` | `is-active hub-worker` = `active` |
| `deploy.worker_log` | 120 s after restart: 0 lines matching `loop error\|Traceback\|hub http 4` |
| `deploy.form_kinds` | `curl -s http://100.85.42.0:3000/hub-form/ \| grep -c 'value="huggingface_repo"'` ≥ 1 (use the path the Pi actually serves `form.html` on; record it) |

## S3 smoke (no restarts or env edits from here on)

Precondition: worker up 2 min, `active_repo` = 0.

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router/homelab/bucket-hub
QC_OUT=/tmp/ap4r1-smoke-qc.json ./scripts/smoke-ap4-hf.sh 2>&1 | tee /tmp/ap4r1-smoke.log
```

| id | expected |
|----|----------|
| `smoke.precheck` … `smoke.missing_repo` | copied unchanged from `QC_OUT`, all `pass` |

## S4 disk checks (after `smoke.h1_done` passes; `<dir>` = its `download_dir`)

```bash
ssh ai-server-ts "cd /mnt/tnas/repo-archive/<dir> && ls -A && ls -la snapshot | head -30 && du -sb snapshot"
ssh ai-server-ts "cd /mnt/tnas/repo-archive/<dir>/snapshot && f=\$(ls -S | head -1); ls -l \$f; head -c 40 \$f | grep -c 'git-lfs' || true"
ssh ai-server-ts "ls -d /mnt/tnas/repo-archive/huggingface-daily/*/.partial-* 2>/dev/null | wc -l"
ssh ai-server-ts "tail -3 /mnt/tnas/repo-archive/download-index.jsonl | jq -c '{kind, status, source_id}'"
```

| id | expected |
|----|----------|
| `live.hf_layout` | folder has `snapshot/`, `README.md`, `.hub-provenance-<id>.json`, `.hub-tags-<id>.json`; `value` = names |
| `live.hf_real_weights` | largest file in `snapshot/` is > 10 000 bytes and the LFS grep count is `0` (spec §T6 step 6); `value` = `{file, bytes, lfs_pointer}` |
| `live.no_partials` | count `0` |
| `live.index_rows` | the tail includes `huggingface_repo` / `archived` / `hf:model/hf-internal-testing/tiny-random-gpt2` |
| `live.token_not_in_ps` | run the r4 sampler (1200 × 0.2 s, `grep -c "hf_"` instead of `Authorization: Bearer`) **during** S3; distinct counts = `0` only. Skip with reason if `HF_TOKEN` is unset |

Afterwards dismiss the smoke jobs (the `JOBS` line in the smoke log) if your tools allow.

## DOCUMENTS TO UPDATE (only these)

- `homelab/bucket-hub/docs/testing/AP-4-test-report.md`: fill "Manual acceptance" from the checks; record `info.legacy_hf_lfs` under "LFS pointer inference".
- `homelab/bucket-hub/docs/testing/AP-3-test-report.md`: §T6 step 6 status from `live.hf_real_weights`.
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`: if `overall` = `pass`, tick AP-4; one session-log row citing `AP-4-r1.json`. Otherwise the row only.
- `CHANGELOG.md`: one line under the AP-4 entry, "Deployed 2026-10-12, QC r1 <overall>".
- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-4-r1.json` (new).
