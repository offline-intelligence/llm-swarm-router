# AP-UX-1 round 2: TV/film destination fix + Finn sign-off (Cursor prompt)

Paste everything below the line into Cursor. Run it now unless AP-4.1 **B5 (phase 2) is actively running**; if it is, wait for B5 to finish first. A Pi restart while the gated job only sits at `awaiting_licence` is safe (jobs are files on disk; S0 checks it).

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). You do not edit application code, tests, `Caddyfile`, `glance.yml` or `scripts/smoke-*.sh`. Failing check → finding with `repro`, stop dependent steps, continue with independent ones. Never print a token or API key.

PM REVIEW OF `AP-UX-1-r1.json`:
- **F2 (R4, blocker) was a PM code bug, not a mount problem.** The repo's `capture-folders.json` maps `magnet` → `nas/inbox`, and `download_presets.load_overrides()` imported that legacy key as an override for the `tv` preset. So TV resolved to TNAS inbox, which aria2 cannot write without `/mnt/media` staging, and which Sonarr does not import from. R1 passed because it only checked availability. **Fix (PM, on `pm/ap-ux-1`):** `tv` and `film` are now `fixed` presets (always Expansion HDD `torrents/`, no overrides); legacy `magnet` and `website` keys are no longer imported. Smoke R1 now also fails if tv/film are not `/mnt/external/movies/torrents` or website is not `website_backups`/`nas_staging`. Tests 277 → 279. No mount change on ai-server.
- **F1 (Caddyfile parity) closed by `OPS-HF1-r2.json` = pass** (19:02, after your r1 at 18:31). Re-check only.
- **Deviation noted:** r1 ran before AP-4.1 r3 although the handoff said after. No harm found; it explains why OPS-HF1 r2 saw `?v=20261012ux1` live. The Pi app has run `pm/ap-ux-1` code since 18:31.
- `info.radarr_path` / R0: Sonarr and Radarr both returned `ConnectionResetError`, so R0 compared nothing for *arr. Retry once in this round (below); if still reset, record it and move on (not a blocker; Jellyfin was compared).

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (`bucket-hub-qc/v1`).

OUTPUT: `homelab/bucket-hub/docs/pm/2026-10/qc/AP-UX-1-r2.json` (new; leave r1 unchanged), committed on `pm/ap-ux-1`, pushed (PR #8). Reply = that JSON in one ```json block, then at most 5 lines. At S4 reply with the partial JSON (`overall` = `blocked`, reason `awaiting Finn R5`) and wait.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/2026-10/qc/AP-UX-1-r1.json`
2. `homelab/bucket-hub/docs/testing/AP-UX-1-test-report.md` ("Round 2 fix")
3. `homelab/bucket-hub/docs/pm/2026-10/handoffs/AP-UX-1.md` (S1–S4 are reused)
4. `homelab/bucket-hub/docs/agent-context/01-ARCHITECTURE-AND-NETWORK.md` § Remote review (Tailscale URLs)

## INPUT

| Key | Value |
|-----|-------|
| branch / PR | `pm/ap-ux-1` / #8 (draft, base `pm/ap-4.1`). Do not rebase this round |
| PM commit | "fix(hub): AP-UX-1 r2 pin TV/film to torrents/" on top of `fa1f1e2` (`git log --oneline -3`) |
| Hub | `http://100.85.42.0:3000` (Tailscale) |
| deploy | `[pi]` only (`download_presets.py` changed). Gateway: `glance.yml` only if its live diff is `?v=` alone (expected `20261012hf1` live → `20261012ux1` repo) |
| carried | `git.pr`, `smoke.r3_hf_preset` from r1 (`"evidence": "carried from AP-UX-1-r1.json"`) |

## S0 git + unit + gated job

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
git checkout pm/ap-ux-1 && git pull --ff-only && git log --oneline -3
cd homelab/bucket-hub && PYTHONPATH=. python3 -m pytest -q 2>&1 | tail -1
curl -s http://100.85.42.0:3000/api/jobs/7407b085aa83 | jq -c '{status, gate: .gate.state}'
```

| id | expected |
|----|----------|
| `unit.pytest` | `279 passed` (or more), 0 failed |
| `git.push` | pushed |
| `info.gate_job_before` | `{status, gate}` of the AP-4.1 job (expected queued / awaiting_licence, or later if Finn accepted) |

## S1 snapshot BEFORE deploy

As `AP-UX-1.md` S1 (`PHASE=before QC_OUT=/tmp/apux1r2-before.json`, log `/tmp/apux1r2-before.log`). Checks `smoke.r0_snapshot`, `smoke.r0b_snapshot`.

R0 reads Sonarr/Radarr on the worker host from `SONARR_URL` / `RADARR_URL` in `hub-worker.env` (default `http://127.0.0.1:8989` / `:7878`); r1 got `ConnectionResetError` for both. Before S1, find out why (names, ports and codes only; never print keys):

```bash
ssh ai-server-ts 'f=~/homelab/scripts/hub-worker.env; ls -l "$f" | cut -c1-10; grep -oE "^(SONARR|RADARR|JELLYFIN)_URL=.*" "$f" || echo "no *_URL lines (script uses 127.0.0.1 defaults)"; docker ps --format "{{.Names}} {{.Ports}}" | grep -iE "sonarr|radarr|gluetun"; for p in 8989 7878; do curl -s -o /dev/null -w "$p %{http_code}\n" -m 5 http://127.0.0.1:$p/ping; done'
```

`info.arr_reachable` = `{url_lines, containers, ping_codes}` (`WORKER_HOST` in the script is the host to use if it is not `ai-server-ts`). If R0 still shows `ConnectionResetError`, record it in `deviations` (not a blocker this round; PM fixes the script next round).

## S2 deploy

As `AP-UX-1.md` S2. Checks `deploy.pi_parity`, `deploy.pi_app_reloaded`, `deploy.gateway_parity` (exit 0; F1 closed by OPS-HF1 r2), `deploy.presets_endpoint`. Then:

```bash
curl -s http://100.85.42.0:3000/api/presets | jq -c '[.presets[] | select(.id=="tv" or .id=="film" or .id=="website") | {id, path: .destination.path, folder: .destination.folder_id}]'
curl -s http://100.85.42.0:3000/api/jobs/7407b085aa83 | jq -c '{status, gate: .gate.state}'
```

| id | expected |
|----|----------|
| `deploy.tv_film_path` | tv and film `path` = `/mnt/external/movies/torrents`; website folder `website_backups` |
| `info.gate_job_after` | same status/gate as `info.gate_job_before` (a restart must not change it) |

## S3 smoke AFTER deploy

As `AP-UX-1.md` S3 with `QC_OUT=/tmp/apux1r2-after.json`, log `/tmp/apux1r2-after.log`, `R3_WAIT_S=600`. Checks `smoke.r0_connections`, `smoke.r0b_jobs`, `smoke.r1_presets`, `smoke.r2_resolve`, `smoke.r4_manual` = pass (R3 runs again; record `smoke.r3_hf_preset` from this run, replacing the carried value). `info.radarr_path` as before. Dismiss the smoke jobs afterwards.

## S4 Finn checks the Download tab (R5)

Ask Finn in chat, using **`http://100.85.42.0:3000/`** (hard refresh), the four questions in `AP-UX-1.md` S4, plus:
5. Paste a magnet link: "Saves to" says **Expansion HDD › torrents**, and queueing gives no `escAttr` error.

`ui.presets` = his words, verbatim, short.

## overall

`pass` only if every non-`info` check is `pass`.

## DOCUMENTS TO UPDATE (only these)

- `homelab/bucket-hub/docs/pm/2026-10/qc/AP-UX-1-r2.json` (new).
- `homelab/bucket-hub/docs/testing/AP-UX-1-test-report.md`: "Manual acceptance" r2 row.
- `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`: one session-log row citing the file; tick the AP-UX-1 backlog line if `pass`.
- `homelab/bucket-hub/TODO.md`: tick the AP-UX-1 line if `pass`.
- `CHANGELOG.md`: one line under the AP-UX-1 entry, "QC r2 <overall>".
- If `pass`: `gh pr ready 8` (do not merge; #8 merges after #7).
