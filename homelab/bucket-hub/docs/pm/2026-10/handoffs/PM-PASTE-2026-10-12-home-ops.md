# Paste for Claude PM — home ops 2026-10-12

Copy everything below the line into the Homelab PM session.

---

## READ FIRST (in order)

1. `homelab/bucket-hub/docs/agent-context/PROJECT-STATE.md`
2. `homelab/bucket-hub/docs/testing/AP-3-test-report.md` — §T6 home re-run
3. `homelab/bucket-hub/docs/REPO-ARCHIVE.md`
4. PR: `cursor/ops-2026-10-12-home` on `offline-intelligence/llm-swarm-router`

---

## CONTEXT UPDATE

### Last updated
2026-10-12 (Cursor home ops pass)

### Session log (append)

| Date | Event |
|------|--------|
| 2026-10-12 | **Mac SSH:** `stackrise-pi` → `HostName 100.85.42.0`; parity script works. |
| 2026-10-12 | **TNAS IP:** tracked files `.186` → `.187`; Pi `~/homelab/data/hub-jobs/machines.json` + `hub-form/glance.yml` deployed; `TNAS_HOST=.187` on ai-server. |
| 2026-10-12 | **Pi deploy:** manifest rsync, `hub-form` active, `verify-deploy-parity.sh pi` **0**. Glance `glance.yml` copied to `~/homelab/glance/`; iframe `?v=20261012ops1`. |
| 2026-10-12 | **Uptime Kuma:** `uptime-kuma-bootstrap.py` only **adds** missing monitors — Finn must edit existing **TNAS** URL in UI to `http://192.168.50.187:8181/`. |
| 2026-10-12 | **`HUB_GITHUB_TOKEN`:** still **unset** (Finn to add). |
| 2026-10-12 | **§T6 step 2 baseline:** **fail** — Debian torrent job errored; Spoon-Knife repo queued 120s while `active_repo=1` (duplicate clone running). Re-test after AP-3.1. |
| 2026-10-12 | **AP-3.1 note:** `gluetun_http_json` still passes token in `docker run` argv (do not fix in ops). |

### Backlog changes

- [x] Pi SSH alias + `.187` repo sweep (ops PR).
- [ ] Router DHCP reservation for TNAS.
- [ ] `HUB_GITHUB_TOKEN` in `hub-worker.env`.
- [ ] Uptime Kuma TNAS monitor URL (UI).
- [ ] §T6 step 2 acceptance (AP-3.1).

### Decisions changed

- none

---

## Request

1. Review ops PR `cursor/ops-2026-10-12-home`.
2. Confirm AP-3.1 priority before Finn re-runs §T6 step 2.
3. Emit **## CONTEXT UPDATE** if anything above should move into decisions.
