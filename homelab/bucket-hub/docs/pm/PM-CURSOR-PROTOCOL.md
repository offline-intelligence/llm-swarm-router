# PM ↔ Cursor protocol (from 2026-10-12)

Applies to every Bucket-HUB packet from AP-3.1 on. Machine-readable first; prose only where a field says so.

## Roles

| Role | Owns | Never does |
|------|------|------------|
| **PM (Claude, folder thread)** | Specs, application code, unit tests, smoke scripts, docs, the branch `pm/<packet>` (committed locally on the Mac), fixes for every QC finding | SSH, deploy, push (no GitHub access from the PM session) |
| **Cursor (Mac)** | Integrate: fetch, rebase, run tests, push, open draft PR, deploy, run smokes, collect evidence, return a **QC report** | Edit application code, tests or smoke scripts to make them pass. On failure: stop, report, wait for the PM |
| **Finn** | Secrets and env values, router/NAS/UI changes, approvals, pasting between PM and Cursor | — |

Cursor may edit only: docs listed in the packet's DOCUMENTS TO UPDATE, `CHANGELOG.md`, `PROJECT-STATE.md` ticks and session log, merge-conflict resolution in docs.

## Loop

```text
PM: code + tests on pm/<packet>  ->  handoff docs/pm/<yyyy-mm>/handoffs/<packet>.md
Finn: paste handoff into Cursor
Cursor: integrate -> test -> deploy -> smoke -> write QC report JSON -> reply with it
Finn: paste QC report into the PM thread
PM: overall=pass -> next packet;  overall=fail|blocked -> fix commit on pm/<packet>, new handoff (round+1)
```

## QC report

Cursor writes it to `homelab/bucket-hub/docs/pm/<yyyy-mm>/qc/<packet>-r<round>.json`, commits it on the packet branch, and pastes the **same JSON** as the first block of its reply, inside a ```json fence. No prose before it.

### Schema `bucket-hub-qc/v1`

```json
{
  "schema": "bucket-hub-qc/v1",
  "packet": "AP-3.1",
  "round": 1,
  "generated_at": "2026-10-12T03:00:00+10:00",
  "git": {
    "branch": "pm/ap-3.1",
    "head": "<sha after rebase>",
    "base": "offline-intelligence/main@<sha>",
    "pr_url": "<url or null>",
    "rebase_conflicts": ["<path>"]
  },
  "overall": "pass | fail | blocked",
  "checks": [
    {
      "id": "<check id from the handoff>",
      "status": "pass | fail | skip | blocked",
      "value": "<number | string | object | null>",
      "expected": "<from the handoff>",
      "evidence": "<one line: command + key output, no secrets>",
      "log": "<path to full log or null>"
    }
  ],
  "findings": [
    {
      "id": "F1",
      "severity": "blocker | major | minor | nit",
      "check": "<check id or null>",
      "where": "<file:line | host:service | url>",
      "observed": "<exact output, trimmed>",
      "expected": "<what the handoff said>",
      "repro": "<exact command>",
      "suspect": "<Cursor's hypothesis, optional>"
    }
  ],
  "needs_finn": ["<action only Finn can take>"],
  "deviations": ["<anything done differently from the handoff, and why>"],
  "docs_updated": ["<path>"]
}
```

### Rules

- Every check id listed in the handoff appears exactly once in `checks`. Unreached checks are `skip` with `evidence: "not reached"`; checks waiting on Finn are `blocked`.
- `overall` = `pass` only if every check is `pass`. Any `fail` → `fail`. Otherwise any `blocked` → `blocked`.
- Every `fail` has a matching `findings` entry with a `repro` command.
- pytest evidence: the final summary line verbatim (e.g. `177 passed in 4.1s`) plus failing test node ids in `value`.
- Smoke scripts print `QC {json}` lines and write a JSON array (`QC_OUT`); copy those objects into `checks` unchanged.
- Parity evidence: exit code in `value`, mismatched paths in `evidence`.
- Logs: save full output under `/tmp/<packet>-*.log` on the Mac and reference the path; never paste env files, tokens or `~/.ssh` content. Redact anything matching `ghp_`, `github_pat_`, `hf_`, `Bearer `.
- Times in `Australia/Brisbane` ISO-8601.
