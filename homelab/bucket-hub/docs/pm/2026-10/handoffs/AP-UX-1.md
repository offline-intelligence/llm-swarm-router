# AP-UX-1 round 1: download presets and segments (Cursor prompt)

Paste everything below the line into Cursor **after `AP-4.1-r3.json` is final** (pass, or blocked only on HF approval with phase 2 not running). Deploying restarts the Pi app, which must not happen during the AP-4.1 smoke.

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). You do not edit application code, tests, `Caddyfile`, `glance.yml` or `scripts/smoke-*.sh`. Failing check → finding with `repro`, stop dependent steps, continue with independent ones. Never print a token or API key.

WHAT THIS IS: Finn's "download segments with pre-defined paths". The Hub now has 8 presets in 4 segments (TV & film · Repo archive · Websites · Other). The server decides where each lands; Drive/Folder only appear behind "Manually set path". No new downloader: every preset maps to a job kind the worker already runs. **Worker unchanged; no worker deploy or restart.**

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (`bucket-hub-qc/v1`).

OUTPUT: `homelab/bucket-hub/docs/pm/2026-10/qc/AP-UX-1-r1.json`, committed on `pm/ap-ux-1`, pushed. Reply = that JSON in one ```json block, then at most 5 lines.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/2026-10/AP-UX-1-download-presets.md` (incl. "As built")
2. `homelab/bucket-hub/docs/testing/AP-UX-1-test-report.md` ("Behaviour changes to know about")
3. `homelab/bucket-hub/docs/agent-context/05-OPERATIONS-SSH-DEPLOY.md` (Pi + Gateway sections)

## INPUT

| Key | Value |
|-----|-------|
| branch | `pm/ap-ux-1` (local, on top of `pm/ap-4.1`; PM commit "feat(hub): AP-UX-1 …") |
| PR | open a **draft** PR `pm/ap-ux-1` → base `pm/ap-4.1` if #7 is not merged yet, else base `main` (rebase onto `main` first; conflicts → finding, do not resolve) |
| deploy | `[pi]` (new file `download_presets.py`) + `[gateway]` (`glance.yml` `?v=20261012ux1`) |

## S0 git + unit

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
git checkout pm/ap-ux-1 && git log --oneline -3
cd homelab/bucket-hub && python3 -m pytest -q 2>&1 | tail -2
```

| id | expected |
|----|----------|
| `unit.pytest` | `277 passed` (or more), 0 failed |
| `git.push` / `git.pr` | pushed; draft PR url |

## S1 snapshot BEFORE deploy (read-only)

```bash
PHASE=before QC_OUT=/tmp/apux1-before.json ./scripts/smoke-apux1-presets.sh 2>&1 | tee /tmp/apux1-before.log
```

Checks `smoke.r0_snapshot`, `smoke.r0b_snapshot` = pass. Also record the live library ids the presets match on (ids and rels only):

```bash
curl -s http://100.85.42.0:3000/api/library | jq -c '[.drives | to_entries[] | {id: .key, root: .value.root, mounted: .value.mounted, folders: [.value.folders[]? | {id, rel, present}]}]'
```

`info.library_ids` = that output.

## S2 deploy

```bash
# Pi app
rsync the [pi] manifest set to stackrise-pi:~/homelab/hub-form/   (as in earlier rounds)
ssh stackrise-pi 'systemctl --user restart hub-form.service'
./scripts/verify-deploy-parity.sh pi; echo "exit=$?"
# Gateway (glance.yml cache-buster only; Caddyfile unchanged since OPS-HF1)
ssh stackrise-pi 'cat ~/homelab/glance/glance.yml' | diff - glance.yml   # expect only the ?v= line
scp glance.yml stackrise-pi:~/homelab/glance/ && ssh stackrise-pi 'docker restart glance'
./scripts/verify-deploy-parity.sh gateway; echo "exit=$?"
```

| id | expected |
|----|----------|
| `deploy.pi_parity` | exit 0 |
| `deploy.pi_app_reloaded` | process start later than `app.py` mtime (method as AP-4-r1b) |
| `deploy.gateway_parity` | exit 0 (glance.yml diff was only `?v=`; anything else → stop, finding) |
| `deploy.presets_endpoint` | `curl -s -o /dev/null -w '%{http_code}' http://100.85.42.0:3000/api/presets` = `200` |

## S3 smoke AFTER deploy

```bash
PHASE=after QC_OUT=/tmp/apux1-after.json ./scripts/smoke-apux1-presets.sh 2>&1 | tee /tmp/apux1-after.log
```

Checks `smoke.r0_connections`, `smoke.r0b_jobs`, `smoke.r1_presets`, `smoke.r2_resolve`, `smoke.r3_hf_preset`, `smoke.r4_manual` = pass. R1 may show a preset `available: false` only when its reason names an offline drive (e.g. TNAS asleep); record which.

`info.radarr_path`: from the R0 value, Radarr's download-client directory and root folders (paths only). PM uses it to confirm the film preset.

Dismiss the smoke jobs (`JOBS` line) afterwards.

## S4 Finn checks the Download tab (R5)

Ask Finn, in chat, to open the Hub (hard refresh) and confirm:
1. The Download tab shows **Download type** chips in four rows (TV & film · Repo archive · Websites · Other) and a **Saves to** line; no Drive/Folder chips.
2. Pasting a GitHub link shows "Saves to: TNAS repo archive › github-daily"; a magnet shows "Expansion HDD › torrents".
3. Ticking **Manually set path** shows Drive and Folder; unticking hides them.
4. The queue panel has the segment filter (All · TV & film · Repo archive · Websites · Other).

`ui.presets` = his words, verbatim, short.

## overall

`pass` only if every non-`info` check is `pass`.

## DOCUMENTS TO UPDATE (only these)

- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-UX-1-r1.json` (new).
- `homelab/bucket-hub/docs/testing/AP-UX-1-test-report.md`: fill "Manual acceptance".
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`: one session-log row citing the file; tick the AP-UX-1 backlog line if `pass`.
- `homelab/bucket-hub/TODO.md`: tick the AP-UX-1 line if `pass`.
- `CHANGELOG.md`: one line under the AP-UX-1 entry, "Deployed 2026-10-12, QC r1 <overall>".
