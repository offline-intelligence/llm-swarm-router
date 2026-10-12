# OPS-ARR2 round 1: worker → Sonarr/Radarr (Cursor prompt)

Paste everything below the line into Cursor. Run it **after AP-5a.1 r3 has merged PR #11** (`pm/ops-arr2` is stacked on `pm/ap-5a1-r3`).

---

ROLE: integrator / deployer / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). Do not edit application code, tests, `Caddyfile`, `glance.yml` or `scripts/smoke-*.sh`. **Finn sets env values**: you print the exact non-secret line to add, Finn adds it. Never print an API key or token. If a check fails, record a finding with `repro`, stop the steps that depend on it, and carry on with the independent ones.

PM REVIEW OF FINN'S PASTE (`handoffs/PM-PASTE-2026-10-12-sonarr-import.md`):
- **Root cause accepted, cause of the reset not yet proven.** The worker on the host gets `Connection reset by peer` from `127.0.0.1:8989`, and the API answers inside the container. Three explanations fit:
  - Sonarr/Radarr still on a namespace that a Gluetun restart left dead;
  - `BindAddress` = 127.0.0.1;
  - the loopback proxy failing while the LAN IP works.
  
  S1 tells them apart, read-only.
- **OPS-ARR1 is folded into OPS-ARR2** (same fault).
- **PM fix** (commit on the local branch `pm/ops-arr2`, spec `docs/pm/2026-10/OPS-ARR2-arr-reachability.md`):
  - new `arr_client.py`: HTTP as now, or `SONARR_VIA_DOCKER=sonarr` → `docker exec sonarr curl -K -`, with the key on stdin;
  - the pipeline records `api_unreachable` separately from `add_failed`, plus `sonarr_scan` / `radarr_scan`;
  - new queue copy, **Library import failed: Sonarr not reachable**;
  - `job_health` code `sonarr_unreachable`;
  - the Hub worker token is no longer sent to *arr;
  - new smoke `scripts/smoke-ops-arr2.sh`.
  
  Tests 301 → 316.

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (`bucket-hub-qc/v1`).

OUTPUT: `homelab/bucket-hub/docs/pm/2026-10/qc/OPS-ARR2-r1.json`, committed on `pm/ops-arr2`, pushed, draft PR to `main`. Reply = that JSON in one ```json block, then at most 5 lines. If S3 needs Finn, reply with the partial JSON (`overall` = `blocked`, reason `awaiting Finn env line`), the line(s) to add, and wait.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/2026-10/OPS-ARR2-arr-reachability.md` ("Choosing the transport" table)
2. `homelab/bucket-hub/docs/MEDIA-JELLYFIN-PIPELINE.md` § 7 Worker → Sonarr/Radarr

## S0 git + unit

Your checkout has the PM paste untracked and two uncommitted PROJECT-STATE lines about it. `pm/ops-arr2` contains both, so drop the local copies first, then confirm they are identical:

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router
H=homelab/bucket-hub
git show pm/ops-arr2:$H/docs/pm/2026-10/handoffs/PM-PASTE-2026-10-12-sonarr-import.md | cmp - $H/docs/pm/2026-10/handoffs/PM-PASTE-2026-10-12-sonarr-import.md && rm $H/docs/pm/2026-10/handoffs/PM-PASTE-2026-10-12-sonarr-import.md
git checkout -- $H/docs/agent-context/PROJECT-STATE.md
git fetch offline-intelligence main && git checkout pm/ops-arr2 && git rebase offline-intelligence/main && git log --oneline -3
cd $H && uv pip install "huggingface_hub==0.26.2" && PYTHONPATH=. uv run python -m pytest -q 2>&1 | tail -1
git push -u offline-intelligence pm/ops-arr2
gh pr create --draft --base main --head pm/ops-arr2 --title "OPS-ARR2: worker reaches Sonarr/Radarr; api_unreachable vs add_failed"
```

If `cmp` differs, keep your file, record a `deviation`, and do not delete it.

| id | expected |
|----|----------|
| `unit.pytest` | `316 passed`, 0 failed |
| `git.rebase` | onto `main` (PR #11 merged): only the OPS-ARR2 commit sits above `main`. A conflict in `PROJECT-STATE.md`, `CHANGELOG.md` or `TODO.md` only: keep both sides' lines (newest session row first) and record it in `deviations`; a conflict anywhere else: stop and report |
| `git.pr` | draft PR URL |

## S1 diagnose (read-only, before deploy)

```bash
cd ~/Documents/AI-ADVANTAGE/Cursor_Projects/llm-swarm-router/homelab/bucket-hub
QC_OUT=/tmp/opsarr2-before.json ./scripts/smoke-ops-arr2.sh 2>&1 | tee /tmp/opsarr2-before.log
ssh ai-server-ts 'id -nG | tr " " "\n" | grep -x docker || echo "not in docker group"; systemctl --user show hub-worker -p User -p ActiveState 2>/dev/null || systemctl show hub-worker -p User -p ActiveState'
```

M1 fails here, because `arr_client.py` is not deployed yet. That is expected. Record only D1.

| id | expected |
|----|----------|
| `info.d1_before` | the two D1 rows as printed |
| `info.worker_docker` | whether the worker's user can run `docker` |
| `info.root_cause` | which row of the spec's "Choosing the transport" table matches, for each app, with the D1 fields that decided it |

## S2 deploy

```bash
./scripts/verify-deploy-parity.sh worker   # before deploy: arr_client.py missing is expected
```

Deploy `[worker]` (`hub-worker.py`, `job_health.py`, `arr_client.py`) and `[pi]` (`form.html`, `job_health.py`) as in earlier rounds. Deploy `[gateway]` too: `glance.yml` only, if its live diff is `?v=` alone (`20261012g42` → `20261012arr2`). Restart `hub-worker`.

| id | expected |
|----|----------|
| `deploy.worker_parity` / `deploy.pi_parity` / `deploy.gateway_parity` | exit 0 each |
| `deploy.worker_service` | active, no traceback in the first 2 min of `journalctl` |

## S3 fix the path (per spec table)

For each app, apply the first matching row:
- `netns_current` = false: run `ssh ai-server-ts 'docker restart sonarr radarr'`, wait 30 s, re-run S1's smoke, then re-pick the row.
- An env change: send Finn the exact line, for example `SONARR_VIA_DOCKER=sonarr` or `SONARR_URL=http://<lan_ip>:8989`. Wait for him to add it and confirm. Then restart `hub-worker`.

Never change `*_API_KEY` lines.

| id | expected |
|----|----------|
| `ops.arr_fix` | what was done per app (none / restart / env line name, never its value if secret) |

## S4 smoke after

```bash
QC_OUT=/tmp/opsarr2-after.json ./scripts/smoke-ops-arr2.sh 2>&1 | tee /tmp/opsarr2-after.log
ssh ai-server-ts 'cd ~/homelab/scripts && set -a && . ./hub-worker.env && set +a && python3 -c "
import arr_client
t = arr_client.target(\"sonarr\")
r = arr_client.request(t, \"POST\", \"/api/v3/command\", {\"name\": \"DownloadedEpisodesScan\", \"path\": \"/data/torrents/The.Office.US.S03.1080p.BluRay.x265-RARBG\"})
print(t.transport, r.get(\"name\"), r.get(\"status\"))
"'
```

The second command re-scans an already imported season. That is harmless: Sonarr skips files it already has. It proves the worker's POST path end to end.

| id | expected |
|----|----------|
| `smoke.d1_paths` | pass |
| `smoke.m1_arr_check` | pass: sonarr and radarr `code` = `ok` with the chosen transport |
| `smoke.m2_scan_command` | prints `<transport> DownloadedEpisodesScan queued` (or `started`/`completed`) |

## S5 Finn (optional, at the next TV download)

The queue row of the next TV torrent reads **In library**, and the episodes appear in Jellyfin. Record `ui.next_tv_import` = his words, or `skip` ("no TV download yet"). Not a blocker.

## overall

`pass` only if every non-`info`, non-`ui` check is `pass`. If `pass`: `gh pr ready <n>`. **Do not merge**; the PM names the merge.

## DOCUMENTS TO UPDATE (only these)

- `qc/OPS-ARR2-r1.json` (new).
- `docs/testing/OPS-ARR2-test-report.md`: "Manual acceptance" r1 row (root cause + fix).
- `docs/agent-context/PROJECT-STATE.md`: one session-log row citing the file; tick the OPS-ARR2 backlog line if `pass`.
- `TODO.md`: tick the OPS-ARR2 line if `pass`.
- `CHANGELOG.md`: "Deployed 2026-10-12, QC r1 <overall>" under OPS-ARR2.
