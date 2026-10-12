# AP-4.2 — Hugging Face access: progressive re-check schedule

**Status:** built by PM 2026-10-12 on `pm/ap-4.2` (base `pm/ap-ux-1`). **Follows:** AP-4.1 (`AP-4.1-hf-gated-access.md`). **Asked by:** Finn, 2026-10-12, after accepting the Gemma and Llama licences.

## Problem

AP-4.1 re-checks a gated job every `HF_GATE_RECHECK_S` (600 s). After Finn accepts on huggingface.co he waits up to 10 min, or clicks Check now. Finn wants: re-check 1 min after the job parks, then 5 min later, then 30 min later, then hourly until access or timeout. Check now stays. Live QC also showed a job that had got access still carrying `gate.state = awaiting_licence` while it downloaded.

## Decisions (PM)

| Topic | Decision |
|-------|----------|
| Schedule | Gaps after each failed check: **60 s, 300 s, 1800 s, then 3600 s repeating** (cumulative 1, 6, 36, 96, 156 … min). `HF_GATE_SCHEDULE_S` (comma list) overrides; a lone legacy `HF_GATE_RECHECK_S` still means a fixed gap. Each gap ≥ 30 s. `HF_GATE_MAX_WAIT_H` (168 h) unchanged |
| Position | The schedule position is `gate.checks`. Check now does not reset it: a failed manual check moves to the next gap (no hammering HF) |
| States | Unchanged contract: `awaiting_licence` / `needs_token` while waiting; new **`granted`** once the probe succeeds (adds `granted_at`, `next_check: null`); `gate` is cleared on done as before. No separate `awaiting_approval` state: a HEAD 403 looks the same whether or not the request was sent or is pending, so the worker cannot tell. The difference is copy, keyed on `gate.gated` (`auto` / `manual`) |
| Packet / branch | `pm/ap-4.2` on top of `pm/ap-ux-1`; PR base `pm/ap-ux-1`. Merge order #7 → #8 → AP-4.2 |

## State machine (`job.gate`)

```text
(no gate) --claim, gated, HEAD 401/403--> awaiting_licence   (or needs_token if no HF_TOKEN)
awaiting_licence --each claim after not_before: HEAD denied--> awaiting_licence, checks+1, not_before = now + gap(checks)
awaiting_licence --Check now (Pi)--> same state, not_before removed, next_check = now
awaiting_licence --HEAD ok--> granted (status running, granted_at, next_check null, error_display cleared)
granted --download done--> (gate cleared; index gate_wait_s = done-time − since, licence_accepted_by = user)
granted --gated error mid-download--> awaiting_licence (AP-4.1 G6)
any waiting state --now − since > HF_GATE_MAX_WAIT_H--> error "Licence not accepted within 168 h"
```

`gate.next_check` always equals `not_before` while waiting. The worker polls every `WORKER_POLL_S` (8 s), so a 60 s gap is honoured to within ~8 s.

## Copy (British English)

| Where | `gated: auto` | `gated: manual` |
|-------|---------------|-----------------|
| Status pill | Licence needed | Approval needed |
| Card | "Licence needed. Accept the licence on Hugging Face; the download starts by itself once access is granted. Next automatic check in N min." | "Approval needed. Request access on Hugging Face; the model owner approves requests by hand, which can take days. Next automatic check in N min." |
| Button | Accept licence | Request access |
| Queue bar | "Waiting for Hugging Face access (N)" + per row "Next automatic check in N min" | same |
| Worker note (unchanged, smoke contract) | "Waiting for licence: accept at <url>" | "Waiting for the model owner to approve access: <url>" |
| Once granted | progress note "Access granted, starting download" | same |

## Operator flow

1. Queue the gated repo. Within one worker poll the card shows Licence needed / Approval needed.
2. Click Accept licence / Request access, sign in to huggingface.co **as the account that owns the worker's `HF_TOKEN`**, accept or request.
3. Wait: the Hub re-checks on the schedule above. Or click Check now for an immediate check.
4. When access exists the card changes to downloading; the licence bar drops the row.

## Tests (`tests/test_repo_archive_hf_gate.py`)

| Id | Test |
|----|------|
| S1 | `test_s1_default_schedule_1_5_30_then_hourly` (6 claims → gaps 60, 300, 1800, 3600, 3600, 3600) |
| S2 | `test_s2_schedule_from_env`, `test_s2_legacy_fixed_gap` |
| S3 | `test_s3_check_now_keeps_the_schedule_position` |
| S4 | `test_s4_granted_state_while_downloading`, `test_s4_no_granted_update_for_first_time_access` |
| S5 | `test_s5_form_copy_and_waiting_filter` |

G2 now expects the first gap of 60 s (was 600 s).

## Out of scope (backlog)

- Dedupe of repeated queue clicks for the same URL (Finn saw duplicate done jobs).
- Size warning or policy for large ungated third-party HF repos.
