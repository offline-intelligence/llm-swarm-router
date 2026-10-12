# Paste for Claude PM — Hub UI blocked (`escAttr` / queue) + QC plan (2026-10-12)

Copy everything below the line into the Homelab PM session.

---

## CONTEXT UPDATE

### Last updated
2026-10-12 (Finn evening; away-from-home review on Tailscale)

### Session log (append)

| Date | Event |
|------|--------|
| 2026-10-12 | **Finn live check (AP-UX-1):** Glance Hub at Tailscale `:3000` shows empty Download type chips, queue **"Could not load queue"**, queueing GitHub URL → **`escAttr is not defined`**. Same root cause as OPS-HF1: `GET :3000/assets/hub-escape.js` → **404**; `:3020/assets/hub-escape.js` → **200**. Presets API OK (`GET :3000/api/presets` → 200). |
| 2026-10-12 | **Finn tried workaround** `http://100.85.42.0:3020/hub-form` (no trailing slash) → FastAPI **`{"detail":"Not found"}`**. Correct direct URL: **`http://100.85.42.0:3020/hub-form/`** (307 from bare `/hub-form/`). Normal UX remains Glance iframe on **:3000** until gateway Caddy is fixed. |
| 2026-10-12 | **QC already on record:** `OPS-HF1-r1.json` **fail** (glance `?v=` drift stopped full gateway copy; Caddy `hub-escape` route not live). `AP-UX-1-r1.json` **fail** (gateway parity + `smoke.r4_manual` 400 on manual tv→`nas/inbox` without `/mnt/media` on ai-server). `AP-4.1-r2.json` **blocked** (no `gated=auto` GATE_REPO; smoke not run). |
| 2026-10-12 | **Remote review (Finn):** Use **Tailscale** Hub URLs while off-LAN; LAN `192.168.50.138:3000` not required. Documented in `01-ARCHITECTURE-AND-NETWORK.md` § Remote review. |

### Decisions changed

| Topic | Decision |
|-------|----------|
| UI review off-LAN | **Tailscale first:** `http://100.85.42.0:3000/` (Glance + iframe). Optional direct form: `http://100.85.42.0:3020/hub-form/` (**trailing slash**). Public `https://bucket-hub.stackrise.com.au` still valid behind Cloudflare Access. |
| P0 before AP-UX-1 R5 / r2 pass | **OPS-HF1 gateway deploy** must land so `:3000` serves `hub-escape.js`. AP-UX-1 Pi code is already deployed; this is not a presets regression. |

### Backlog / priority (PM)

1. **P0 — OPS-HF1 r2 (Cursor):** unblock gateway deploy (see integrator packet below). Finn cannot sign off Download tab until this passes.
2. **P1 — AP-UX-1 r2 (Cursor):** after P0, Finn **R5** verbatim + re-run `smoke-apux1-presets.sh` after; fix or waive **R4** (`smoke.r4_manual`) per PM choice.
3. **P2 — AP-4.1 r3 (Cursor):** PM supplies **`GATE_REPO`** with `gated=auto`, ≤20 GB safetensors, not yet accepted (PM list `google/gemma-2-9b` / `-it` are **`gated: manual`** on HF API — rejected in r2).

---

## STATUS SUMMARY FOR PM

| Packet | QC | Live symptom | Blocker |
|--------|-----|--------------|---------|
| **OPS-HF1** | r1 **fail** | `escHtml` / `escAttr is not defined`, queue broken on `:3000` | Live `~/homelab/glance/Caddyfile` ≠ repo (no `/assets/hub-escape.js` route). `glance.yml` drift was only `?v=` (OK to overwrite on deploy). |
| **AP-UX-1** | r1 **fail** | No Repo archive chips; cannot queue from UI | Depends on OPS-HF1 for Glance path. Separate: **R4** smoke fails (manual magnet to TNAS inbox needs `/mnt/media` on ai-server). PR **#8** draft → `pm/ap-4.1`. |
| **AP-4.1** | r2 **blocked** | Gated HF smoke not run | No valid `GATE_REPO`; PR **#7** draft on `main`. |

**MERGE-1:** #5 and #6 merged to `main`; #7 not merged (QC not pass).

---

## INTEGRATOR PACKET TO AUTHOR (Cursor — do not code)

Please write **`homelab/bucket-hub/docs/pm/2026-10/handoffs/OPS-HF1-r2.md`** (or extend `OPS-HF1-AP-4.1-r2.md`) with:

### Part A — Gateway (P0)

1. PM confirms: on gateway deploy, **overwrite** live `glance.yml` when diff is **only** `?v=` cache-buster (per `PROJECT-STATE` Glance cache-buster decision).
2. **Backup** Pi `~/homelab/glance/Caddyfile` + `glance.yml`.
3. **Copy repo `Caddyfile`** to Pi (includes `handle /assets/hub-escape.js`); copy `glance.yml` if `?v=` only drift.
4. `docker restart hub-gateway glance` (or per `05-OPERATIONS-SSH-DEPLOY.md`).
5. `verify-deploy-parity.sh gateway` → exit 0.
6. Checks: `curl :3000/assets/hub-escape.js` → **200**; body contains `function escHtml`.
7. **Finn / Cursor:** Glance queue loads; Console clean; retry GitHub paste → no `escAttr` error.
8. QC file: `OPS-HF1-r2.json` overall **pass** required before AP-UX-1 r2 can pass UI checks.

### Part B — AP-UX-1 r2 (after Part A pass)

1. No Pi app redeploy unless PM ships a fix; presets already on worker/Pi from r1.
2. Re-run `PHASE=after` `smoke-apux1-presets.sh`.
3. **R4:** PM picks one: (a) change smoke to manual-path test using **Expansion HDD `torrents/`** preset destination; (b) mount/policy fix on ai-server for `/mnt/media`; (c) accept waiver with documented reason (not preferred).
4. Collect Finn **R5** (`ui.presets`) on Tailscale `:3000` after hard refresh.
5. QC: `AP-UX-1-r2.json`; update test report + CHANGELOG.

### Part C — AP-4.1 (parallel only if PM ready)

- New `GATE_REPO` + r3 handoff; do not restart worker mid-smoke.

### DOCUMENTS TO UPDATE (Cursor, when executing)

Per round QC JSON + `PROJECT-STATE.md` session log + `CHANGELOG.md` + relevant `AP-*-test-report.md`.

---

## TAILSCALE URLS (Finn + Cursor QC while off-LAN)

| Use | URL |
|-----|-----|
| Hub (primary) | http://100.85.42.0:3000/ |
| Hub form iframe | http://100.85.42.0:3000/hub-form/ |
| Direct form (debug; trailing slash) | http://100.85.42.0:3020/hub-form/ |
| Presets API | http://100.85.42.0:3000/api/presets |
| Escape script probe (must be 200 after OPS-HF1) | http://100.85.42.0:3000/assets/hub-escape.js |
| SSH | `stackrise-pi` → `100.85.42.0` (see `SSH-PASTE.txt`) |

---

## FINN NOTES (verbatim intent)

- Wants Download segments / presets to work; GitHub/HF are **Repo archive** chips or auto-detect on paste, not a separate top-level mode.
- Going out of house: **use Tailscale URLs above** for UI review until home LAN is back.
- Cursor (agent) travels with Finn on laptop; integrator SSH still uses `stackrise-pi` / Tailscale IP.

---

## ASK PM

1. Confirm **OPS-HF1 r2** handoff scope (Caddyfile deploy + glance `?v=` overwrite OK).
2. Choose **R4** fix path for AP-UX-1 r2.
3. Name **`GATE_REPO`** for AP-4.1 r3 (`gated=auto`, ~20 GB, not accepted).
