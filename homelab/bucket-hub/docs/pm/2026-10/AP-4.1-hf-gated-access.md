# AP-4.1 — Hugging Face gated repos: paste a link, it downloads

**Status:** implemented by the PM on `pm/ap-4.1` (2026-10-12); Cursor deploys and QCs after AP-4 QC r1b passes. Handoff `handoffs/AP-4.1.md`.
**Parent spec:** `cursor-github-hf-downloader.md` (§A4 `huggingface_repo`, §A5 HF). **Builds on:** AP-4 (`repo_archive_hf.py`).

## Product requirement (Finn, 2026-10-12)

Pasting a Hugging Face link into the Hub is the main way models get archived. The Hub is an automatic downloader: a gated model must not end in a dead-end error ("go accept on huggingface.co and retry"). After the URL is queued, the Hub should get the model onto TNAS with at most one click from Finn, and no re-queueing.

## What Hugging Face allows (checked by PM)

- Gating is per repo: `gated` = `false`, `"auto"` (access granted immediately when the user submits the access form) or `"manual"` (the repo owner approves each request). The metadata API returns it.
- Access belongs to the **account**, and the API checks it through the token. Without `HF_TOKEN` no gated file can be fetched, even after the licence is accepted in a browser.
- `huggingface_hub` 0.26.2 has no user-side "accept licence / request access" call. Its access-request functions (`accept_access_request`, `list_pending_access_requests`, …, on `/api/{type}s/{id}/user-access-request/*`) are for the **repo owner** handling other people's requests. The user side is the web form on the model page, which uses a browser login session, not the API token, and some repos add their own required fields (name, affiliation, country, intended use).
- Inferred, not verified (huggingface.co is blocked from the PM container): there is no supported token-only endpoint a user can call to accept a licence. Spike S1 below confirms or refutes this before any auto-accept code is written.

So "accept on Finn's behalf" splits into: (a) everything around the click, which the Hub can fully automate, and (b) the click itself, which is only automatable by driving HF's web form with Finn's browser session.

## Design

### A1 Gate detection before download

In `run_huggingface_repo_job`, after metadata and before the snapshot:

1. If `meta.gated` is falsy → unchanged AP-4 path.
2. If gated and `HF_TOKEN` is unset → state `needs_token` (A2).
3. If gated and a token is set → probe access: `HEAD https://huggingface.co/{prefix}{repo_id}/resolve/{sha}/{probe_file}` with the token (via Gluetun, token over stdin, like the metadata call). `probe_file` = `README.md` if listed, else the smallest sibling. 200/302 → download as normal. 401/403 → state `awaiting_licence` (A2).
4. A `GatedRepoError` / `error_kind: "gated"` from the archiver mid-download (access revoked) also → `awaiting_licence`; the partial folder is removed (the next attempt starts clean anyway).
5. An inconclusive probe (Gluetun error, unexpected status) lets the download decide, so a network blip never parks a job.

### A2 Waiting states, not errors

A gated job without access stays alive:

| field | value |
|-------|-------|
| `status` | `queued` |
| `not_before` | now + next gap of the AP-4.2 schedule (60, 300, 1800, then 3600 s; was a fixed `HF_GATE_RECHECK_S` = 600) |
| `progress.note` | `Waiting for licence: accept at https://huggingface.co/<id>` (or `Needs HF_TOKEN on the worker` for `needs_token`) |
| `gate` (new job field) | `{state: "awaiting_licence"\|"needs_token", gated: "auto"\|"manual", url, since, checks}` |

Each re-claim re-runs A1 only (cheap HEAD, no download). When access appears, `gate` is cleared and the normal AP-4 path runs. After `HF_GATE_MAX_WAIT_H` (default 168, 7 days) the job errors with `Licence not accepted within 7 days` and `resolved: false`. `needs_token` never times out silently: it errors after the same window.

### A3 Hub UI: one click

- Job card with `gate.state == "awaiting_licence"`: an **Accept licence** button (opens `gate.url` in a new tab) and a **Check now** button (`POST /api/jobs/{id}/gate-check` clears `not_before`). Label shows `auto` ("access is instant after you accept") or `manual` ("the model owner approves requests; this can take days").
- ~~On paste: `GET /api/hf/gate`~~ dropped at implementation: the Pi never calls huggingface.co itself (all HF traffic goes through the worker's Gluetun relay), and the job card shows the licence state within one worker claim (seconds) anyway.
- `needs_token`: card says "Add HF_TOKEN to the worker" with a link to `docs/REPO-ARCHIVE.md#hugging-face`.
- A strip on the Hub home lists jobs waiting on a licence, so a batch of pasted links needs one pass of clicks.

### A4 Optional auto-accept — NOT BUILT (Finn chose one click, 2026-10-12)

`HF_AUTO_ACCEPT=1` plus an HF browser session cookie (`HF_SESSION_COOKIE`, worker env, never committed) lets the worker submit the model page's access form for `gated: "auto"` repos whose form has no extra required fields. Repos with extra fields, or `manual` repos, fall back to A3. Every auto-accept is logged in the job (`gate.auto_accepted_at`) and in the index entry (`licence_accepted_by: "hub-auto"`), because accepting a licence is a legal act on Finn's behalf.

Risks: the cookie is a full-account credential (wider than a read token); HF can change the form at any time and break this silently; automated form posts may conflict with HF's terms. Default **off**. Finn decides whether A4 is built at all (see "Decision").

### A5 Index and provenance

The index entry for a gated repo records `gated`, `licence` (from card), `licence_accepted_by` (`"user"` or `"hub-auto"`) and `gate_wait_s`.

## Spike S1 — NOT RUN (only needed for A4)

With Finn's HF account and a throwaway gated `auto` model he has not accepted yet:

1. `curl -sI -H @- https://huggingface.co/<id>/resolve/main/config.json` with the token over stdin → record status (expect 401/403).
2. In a browser, open DevTools → Network, click "Agree and access repository", record the request method, path, content type and form field names (**not** cookie values).
3. Repeat step 1 → expect 200/302.
4. Report `{endpoint, method, fields, needs_cookie, works_with_token_only}` in `docs/pm/2026-10/qc/AP-4.1-spike.json`.

## Acceptance tests

Unit (PM, `tests/test_repo_archive_hf_gate.py`, fake runner and fake HTTP):

| id | case | expected |
|----|------|----------|
| G1 | `gated: false` | no probe, AP-4 path unchanged |
| G2 | gated, no token | `gate.state = needs_token`, `status = queued`, `not_before` set, no runner call |
| G3 | gated, token, probe 403 | `awaiting_licence`, note has the model URL, no runner call |
| G4 | G3 job re-claimed, probe 200 | `gate` cleared, snapshot runs, `done`, index has `licence_accepted_by` |
| G5 | waiting past `HF_GATE_MAX_WAIT_H` | `error`, `error_display = "Licence not accepted within 7 days"` |
| G6 | archiver returns `error_kind: gated` mid-download; probe raises | `awaiting_licence`, partial removed; probe error → download decides |
| G7 | `POST /api/jobs/{id}/gate-check` | clears `not_before`; 404 for a job without `gate` |
| G8 | worker probe | `HEAD` without redirects via Gluetun, token over stdin; `update_job(gate=None)` sends an explicit null |
| G9 | token sampler | `HF_TOKEN` never in argv (`ps`) during probe or download |

Live (Cursor, `scripts/smoke-ap41-gate.sh`, two phases around Finn's click):

| id | case | expected |
|----|------|----------|
| L1 | public model | unchanged, `done` |
| L2 | gated `auto` model Finn has **not** accepted, `HF_TOKEN` set | job shows `awaiting_licence` within one claim; Accept-licence link correct |
| L3 | Finn clicks accept, then **Check now** | job `done` within one re-check, real weights on TNAS (> 10 000 bytes, no LFS pointer) |
| L4 | gated model with `HF_TOKEN` unset | unit test G2 only (a live run would need an env edit + restart mid-QC) |
| L5 | (only if A4 built) gated `auto`, `HF_AUTO_ACCEPT=1` | `done` with no click; `licence_accepted_by = "hub-auto"` |

## Decision (Finn)

**Decided 2026-10-12: One click.** Build A1–A3, A5. A4 auto-accept and spike S1 are out of scope (no session cookie stored); L5 dropped.

Build A4 auto-accept, or stop at A1–A3 (one click per gated model, then it downloads by itself)? PM recommendation: A1–A3 now. They meet "paste and it downloads" for everything except the single licence click, with no session cookie stored. A4 is only worth building if the spike shows a stable form and Finn accepts storing his HF session cookie on the worker.

## Ops prerequisites (Finn)

- `HF_TOKEN` (read scope) in `~/homelab/scripts/hub-worker.env` on ai-server-ts, from the same HF account Finn uses in the browser. Without it no gated model can ever download.
