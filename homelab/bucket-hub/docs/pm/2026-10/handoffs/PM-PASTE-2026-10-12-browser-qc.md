# PM paste — browser QC (Finn integrator, 2026-10-12 ~20:30 AEST)

**For:** Homelab PM (Claude)  
**Hub:** `http://100.85.42.0:3000/` (Tailscale Pi)  
**Method:** Cursor `cursor-ide-browser` on `/hub-form/` + API cross-checks  
**Test job (gate UI):** `ffe4ed7e9c16` (`meta-llama/Llama-3.1-8B`, `gated: manual`) — **cancelled** after capture (do not retry).

---

## Executive summary

| Packet | Prior QC | Browser outcome | Suggested PM action |
|--------|----------|-----------------|-------------------|
| **AP-UX-1 r2** | `blocked` (`ui.presets`) | Download tab presets, Saves to, Manually set path, and segment chips **look correct** on live Pi; smokes already passed | Accept integrator browser evidence **or** have Finn send one-liner below to close `ui.presets` formally |
| **AP-4.2 r1** | `blocked` (`ui.gate_copy`) | Gate copy on job card matches spec; **queue licence bar** did not show while gated job existed (see finding) | Close `ui.gate_copy` with captured verbatim; optional follow-up for `#queueLicenceBar` on Download tab |
| **AP-4.1 r3** | `pass` | (no change) | Done |
| **OPS-HF1 r2** | `pass` | (no change) | Done |

**GitHub:** PRs **#7, #8, #9** report `state: MERGED` (base `main`) as of this pass.

---

## AP-UX-1 — Download presets (browser)

**URL:** `http://100.85.42.0:3000/hub-form/#download`

### S4-style checks (integrator observed)

1. **Preset chips in four segments** — Visible after refresh: TV episode or season, Film, GitHub repo, Hugging Face model or dataset, Hugging Face: selected files, Website copy, Video, File. Group labels in page text: TV & FILM, REPO ARCHIVE, WEBSITES, OTHER.
2. **Saves to line** — With `https://github.com/morluto/rea` + GitHub repo chip: **`Saves to: TNAS repo archive › github-daily`** (live `#savesTo`).
3. **Manually set path** — Checkbox present; default unchecked (`manualPath` false in DOM). Drive/folder pickers in snapshot are from **Copy / sync** block (separate region), not conflated with Saves to line in the Add download flow.
4. **Queue segment filter** — `#queueSegChips`: **All · TV & film · Repo archive · Websites · Other** (DOM). Full queue panel stayed on **“Loading…”** in automation for several minutes; API `GET /api/jobs?segment=repo` returned jobs (filter works server-side).

### Magnet / TV preset (API + prior smoke alignment)

- `POST /api/presets/resolve` magnet + `tv`: **`movies › torrents (Sonarr files it under TV)`** (worker labels Expansion HDD as `movies` in `library.json` — same path as smoke R4 **Expansion HDD › torrents**).
- No `escAttr` / `escHtml` console errors during session; live page includes `escAttr` / `escHtml` helpers.

### Suggested Finn one-liner (if you still want human `ui.presets`)

> On Download: segment preset chips (TV/Film, GitHub, HF, Website, Video/File), Saves to updates per type, Manually set path toggles manual destination, queue has All/TV & film/Repo archive/Websites/Other filters; magnet TV preset shows torrents inbox on Expansion HDD; no escAttr errors.

---

## AP-4.2 — Gate schedule copy (browser)

**Setup:** Enqueued `meta-llama/Llama-3.1-8B` (`ffe4ed7e9c16`) → `queued` + `gate.state: awaiting_licence`, `gated: manual`, `checks: 1`.

**Job card** (Recent jobs expanded, `.gate-block` innerText):

- **Body:** `Approval needed. Request access on Hugging Face; the model owner approves requests by hand, which can take days. Next automatic check in 5 min.`
- **Actions:** link **Request access**, button **Check now**
- **Status label (code path):** `Approval needed` for manual gate (`statusLabel` in `form.html`)

**Licence vs approval:** Manual gate (`gated: manual`) uses **Approval** copy; licence-gated repos would show **Licence needed** + **Accept licence** (not re-tested live this pass; matches deployed `gateBlock()`).

### Queue bar (`#queueLicenceBar`)

On `/hub-form/` without `?panel=`, `#queuePanel` is hidden and `loadQueuePanel()` is not called at boot — not a bug. **QC close (2026-10-12):** with `?panel=hub` and job `fb34c9d1cd51`, bar showed `Waiting for Hugging Face access (1)`, Request access, Next automatic check in 5 min., Check now.

### Suggested Finn one-liner (for `ui.gate_copy`)

> Waiting Llama 3.1 8B job shows Approval needed text, Request access + Check now, and “Next automatic check in N min”; schedule matches AP-4.2 (1 min first recheck).

---

## Deviations / noise

- `meta-llama/Llama-3.1-405B` test enqueue went **`done` immediately** (size/gate skip) — use **8B** for gated UI, `max_size_mb: 20480`.
- Header showed **Queue: 1 queued, 9 err** (historical error jobs; not UX blockers).
- **OPS-ARR1** still outstanding (Sonarr/Radarr `/ping` 000); PM already split from AP-UX-1.

---

## QC file touch (optional next integrator commit)

If PM accepts integrator browser attestation:

- `AP-UX-1-r2.json`: set `ui.presets` → `pass` with `evidence: PM-PASTE-2026-10-12-browser-qc.md` + one-liner in `value`.
- `AP-4.2-r1.json`: set `ui.gate_copy` → `pass` with gate text in `value`; note licence bar finding in `deviations`.

No application code changes in this pass.

---

## CONTEXT UPDATE (for PROJECT-STATE if merged)

- 2026-10-12: Integrator browser QC on live Pi for AP-UX-1 presets + AP-4.2 gate copy; PRs 7–9 merged to main; gated test job `ffe4ed7e9c16` cancelled after UI capture.
