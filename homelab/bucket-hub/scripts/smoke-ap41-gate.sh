#!/usr/bin/env bash
# AP-4.1 acceptance: a gated Hugging Face repo waits for a one-click licence, then downloads.
#
# Two phases, because Finn clicks "Agree" on huggingface.co in between:
#   PHASE=1 GATE_REPO=<org/name of a gated model Finn has NOT accepted> ./scripts/smoke-ap41-gate.sh
#   (Finn accepts the licence at the printed URL)
#   PHASE=2 ./scripts/smoke-ap41-gate.sh
# Needs HF_TOKEN in hub-worker.env (same HF account as the browser). curl + jq on the Mac.
# Optional: HUB (default http://100.85.42.0:3000), WAIT_S (default 3600), STATE, QC_OUT.
#
# Machine output (docs/pm/PM-CURSOR-PROTOCOL.md): one line per check on stdout,
#   QC {"id":"smoke.<check>","status":"pass|fail|skip","value":…,"evidence":"…"}
# and a JSON array of the same objects in $QC_OUT. Exit 0 only if every check passed.
set -uo pipefail

HUB="${HUB:-http://100.85.42.0:3000}"
WAIT_S="${WAIT_S:-3600}"
QC_OUT="${QC_OUT:-/tmp/ap41-gate-qc-phase${PHASE:-1}.json}"
command -v jq >/dev/null || { echo "jq required" >&2; exit 2; }

PHASE="${PHASE:-1}"
STATE="${STATE:-/tmp/ap41-gate-state.json}"
GATE_REPO="${GATE_REPO:-}"
if [[ "$PHASE" == 1 ]]; then CHECKS=(gate_precheck gate_check_404 g_waiting g_waiting_stable); else CHECKS=(g_check_now g_done g_index); fi
echo '[]' > "$QC_OUT"
qc() {  # qc <check> <pass|fail|skip> <value-json> <evidence>
  local obj
  obj="$(jq -nc --arg id "smoke.$1" --arg s "$2" --argjson v "$3" --arg e "$4" \
    '{id:$id, status:$s, value:$v, evidence:$e}')"
  echo "QC $obj"
  jq --argjson o "$obj" '. + [$o]' "$QC_OUT" > "$QC_OUT.tmp" && mv "$QC_OUT.tmp" "$QC_OUT"
}
finish() {
  local id
  for id in "${CHECKS[@]}"; do
    jq -e --arg id "smoke.$id" 'any(.[]; .id == $id)' "$QC_OUT" >/dev/null \
      || qc "$id" skip null "not reached"
  done
  local failed
  failed="$(jq '[.[] | select(.status != "pass")] | length' "$QC_OUT")"
  echo "QC_SUMMARY $(jq -c --arg f "$QC_OUT" \
    '{total: length, pass: ([.[]|select(.status=="pass")]|length), fail: ([.[]|select(.status=="fail")]|length), skip: ([.[]|select(.status=="skip")]|length), file: $f}' "$QC_OUT")"
  [[ "$failed" == 0 ]] && exit 0 || exit 1
}
api() { curl -fsS --max-time 15 "$@"; }
post_job() { api -X POST "$HUB/api/jobs" -H 'Content-Type: application/json' -d "$1" | jq -r '.job.id // empty'; }
job() { api "$HUB/api/jobs/$1"; }
field() { job "$1" | jq -r "$2"; }
hf_body() {  # hf_body <url> <options-json>
  jq -nc --arg u "$1" --argjson o "$2" \
    '{kind:"huggingface_repo", url:$u, title:($u | sub("^https://huggingface.co/"; "")), source:"manual",
      tags:["hf","ap41-smoke"], options:$o}'
}
wait_final() {  # wait_final <job> <seconds>; echoes final status
  local st="" t0
  t0=$(date +%s)
  while (( $(date +%s) - t0 < $2 )); do
    st="$(field "$1" .status)"
    [[ "$st" == "done" || "$st" == "error" ]] && break
    echo "TICK $(job "$1" | jq -c '{id, status, note: .progress.note}')"
    sleep 10
  done
  echo "$st"
}


[[ "$PHASE" == 1 || "$PHASE" == 2 ]] || { echo "PHASE must be 1 or 2" >&2; exit 2; }

if [[ "$PHASE" == 1 ]]; then
  [[ -n "$GATE_REPO" ]] || { qc gate_precheck fail null "GATE_REPO unset (org/name of a gated model Finn has NOT accepted)"; finish; }
  lane="$(api "$HUB/api/repo-lane")" || { qc gate_precheck fail null "GET /api/repo-lane failed"; finish; }
  [[ "$(echo "$lane" | jq -r .active_repo)" == "0" ]] \
    || { qc gate_precheck fail "$(echo "$lane" | jq -c .)" "active_repo must be 0"; finish; }
  qc gate_precheck pass "$(jq -nc --arg r "$GATE_REPO" '{gate_repo:$r}')" "repo lane idle"

  # "Check now" on a job that is not waiting on a licence is a 404.
  P="$(post_job "$(jq -nc '{kind:"huggingface_repo", url:"https://huggingface.co/hf-internal-testing/tiny-random-gpt2", title:"ap41-404", source:"manual", tags:["ap41-smoke"], options:{}}')")"
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$HUB/api/jobs/$P/gate-check")"
  if [[ "$code" == 404 ]]; then qc gate_check_404 pass "$code" "non-gated job"; else qc gate_check_404 fail "$code" "expected 404"; fi
  wait_final "$P" 300 >/dev/null

  # Gated job: must park as queued + gate.awaiting_licence, not error.
  G="$(post_job "$(hf_body "https://huggingface.co/$GATE_REPO" '{"max_size_mb":20480}')")"
  [[ -n "$G" ]] || { qc g_waiting fail null "enqueue failed"; finish; }
  jq -nc --arg g "$G" --arg r "$GATE_REPO" '{job:$g, repo:$r}' > "$STATE"
  t0=$(date +%s); j=""
  while (( $(date +%s) - t0 < 180 )); do
    j="$(job "$G")"
    [[ "$(echo "$j" | jq -r '.gate.state // ""')" != "" || "$(echo "$j" | jq -r .status)" =~ ^(done|error)$ ]] && break
    sleep 5
  done
  if echo "$j" | jq -e --arg r "$GATE_REPO" '.status == "queued" and .gate.state == "awaiting_licence"
      and (.gate.url | endswith($r)) and (.not_before // "" | length) > 0 and (.error_display | test("licen|owner"; "i"))' >/dev/null; then
    qc g_waiting pass "$(echo "$j" | jq -c '{id, status, gate, not_before, error_display}')" "parked, Accept licence link = gate.url"
  else
    qc g_waiting fail "$(echo "$j" | jq -c '{id, status, gate, not_before, error, error_display}')" "expected queued + gate.awaiting_licence (needs_token => HF_TOKEN unset; done => Finn already had access)"
    finish
  fi
  # Nothing is downloaded and it is not re-claimed before not_before.
  sleep 60
  j2="$(job "$G")"
  if echo "$j2" | jq -e '.status == "queued" and .gate.checks == 1' >/dev/null; then
    qc g_waiting_stable pass "$(echo "$j2" | jq -c '{status, checks: .gate.checks}')" "no re-probe inside HF_GATE_RECHECK_S"
  else
    qc g_waiting_stable fail "$(echo "$j2" | jq -c '{status, gate}')" "expected still queued with checks 1"
  fi
  echo "ACTION Finn: open $(echo "$j" | jq -r .gate.url), accept the licence, then run PHASE=2"
  finish
fi

# PHASE 2: after Finn accepted the licence on huggingface.co
[[ -f "$STATE" ]] || { qc g_check_now fail null "no $STATE: run PHASE=1 first"; finish; }
G="$(jq -r .job "$STATE")"
r="$(curl -s -X POST "$HUB/api/jobs/$G/gate-check")"
if echo "$r" | jq -e '.ok == true and (.job.not_before // null) == null' >/dev/null; then
  qc g_check_now pass "$(echo "$r" | jq -c '{id: .job.id, next_check: .job.gate.next_check}')" "not_before cleared"
else
  qc g_check_now fail "$(echo "$r" | jq -c .)" "gate-check failed"
fi
st="$(wait_final "$G" "$WAIT_S" | tail -1)"
j="$(job "$G")"
if [[ "$st" == "done" ]] && echo "$j" | jq -e '(.gate // null) == null' >/dev/null; then
  qc g_done pass "$(echo "$j" | jq -c '{id, download_dir, note: .progress.note}')" "downloaded after one click"
else
  qc g_done fail "$(echo "$j" | jq -c '{id, status, gate, error_display, note: .progress.note}')" "expected done, gate cleared"
  finish
fi
if echo "$j" | jq -e '.index_entry.gated == true and .index_entry.licence_accepted_by == "user" and .index_entry.status == "archived"' >/dev/null; then
  qc g_index pass "$(echo "$j" | jq -c '.index_entry | {source_id, gated, licence_accepted_by, gate_wait_s, revision_sha}')" "index records the licence"
else
  qc g_index fail "$(echo "$j" | jq -c '.index_entry | {status, gated, licence_accepted_by, gate_wait_s}')" "index fields missing"
fi
echo "JOBS $(jq -c . "$STATE")"
finish
