#!/usr/bin/env bash
# AP-4 acceptance (§T6 step 6 plus error paths): huggingface_repo jobs through the Hub API.
#
# Run from the Mac after AP-4 is deployed to both hosts. Needs curl + jq.
# Optional: HUB (default http://100.85.42.0:3000), HF_REPO (default
#           hf-internal-testing/tiny-random-gpt2), WAIT_S (default 900),
#           QC_OUT (default /tmp/ap4-smoke-qc.json)
#
# Machine output (docs/pm/PM-CURSOR-PROTOCOL.md): one line per check on stdout,
#   QC {"id":"smoke.<check>","status":"pass|fail|skip","value":…,"evidence":"…"}
# and a JSON array of the same objects in $QC_OUT. Exit 0 only if every check passed.
# Disk checks (real weights, not LFS pointers) are in the handoff: they need ssh.
set -uo pipefail

HUB="${HUB:-http://100.85.42.0:3000}"
HF_REPO="${HF_REPO:-hf-internal-testing/tiny-random-gpt2}"
WAIT_S="${WAIT_S:-900}"
QC_OUT="${QC_OUT:-/tmp/ap4-smoke-qc.json}"
command -v jq >/dev/null || { echo "jq required" >&2; exit 2; }

CHECKS=(precheck h1_done h1_index h1_no_dup_weights h2_dedupe space_rejected missing_repo)
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
      tags:["hf","ap4-smoke"], options:$o}'
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

# 1. precheck: repo lane idle
lane="$(api "$HUB/api/repo-lane")" || { qc precheck fail null "GET /api/repo-lane failed"; finish; }
[[ "$(echo "$lane" | jq -r .active_repo)" == "0" ]] \
  || { qc precheck fail "$(echo "$lane" | jq -c .)" "active_repo must be 0"; finish; }
qc precheck pass "$(echo "$lane" | jq -c '{slot_repo, active_repo}')" "repo lane idle"

# 2. tiny model archived (refresh so a re-run of the smoke downloads again)
H1="$(post_job "$(hf_body "https://huggingface.co/$HF_REPO" '{"refresh":true,"max_size_mb":500}')")"
[[ -n "$H1" ]] || { qc h1_done fail null "enqueue failed"; finish; }
st="$(wait_final "$H1" "$WAIT_S" | tail -1)"
j1="$(job "$H1")"
if [[ "$st" != "done" ]]; then
  qc h1_done fail "$(echo "$j1" | jq -c '{id, status, error_display, note: .progress.note}')" "$HF_REPO not done in ${WAIT_S}s"
  finish
fi
qc h1_done pass "$(echo "$j1" | jq -c '{id, download_dir, note: .progress.note}')" "$HF_REPO done"

e1="$(echo "$j1" | jq -c '.index_entry // {}')"
if echo "$e1" | jq -e --arg r "$HF_REPO" '.kind == "huggingface_repo" and .status == "archived" and (.revision_sha // "" | length) == 40
    and .source_id == ("hf:model/" + $r) and (.file_summary.files // 0) > 0' >/dev/null; then
  qc h1_index pass "$(echo "$e1" | jq -c '{source_id, revision_sha, size_bytes, source_size_bytes, file_summary, license, pipeline_tag}')" "index entry complete"
else
  qc h1_index fail "$(echo "$e1" | jq -c '{kind, status, source_id, revision_sha, file_summary}')" "index entry missing fields"
fi

# prefer_safetensors: if safetensors were archived, no other weight format was.
by_ext="$(echo "$e1" | jq -c '.file_summary.by_ext // {}')"
if echo "$by_ext" | jq -e 'has(".safetensors") | not' >/dev/null; then
  qc h1_no_dup_weights pass "$by_ext" "repo has no safetensors; nothing to drop"
elif echo "$by_ext" | jq -e '[has(".bin"), has(".h5"), has(".msgpack"), has(".pt"), has(".pth"), has(".ckpt")] | any | not' >/dev/null; then
  qc h1_no_dup_weights pass "$by_ext" "safetensors only"
else
  qc h1_no_dup_weights fail "$by_ext" "other weight formats archived beside safetensors"
fi

# 3. same repo again, no refresh: dedupe, no second download
H2="$(post_job "$(hf_body "https://huggingface.co/$HF_REPO" '{}')")"
st="$(wait_final "$H2" 180 | tail -1)"
note="$(field "$H2" '.progress.note // ""')"
if [[ "$st" == "done" && "$note" == Already\ archived* ]]; then
  qc h2_dedupe pass "$(jq -nc --arg j "$H2" --arg n "$note" '{job:$j, note:$n}')" "dedupe"
else
  qc h2_dedupe fail "$(jq -nc --arg j "$H2" --arg s "$st" --arg n "$note" '{job:$j, status:$s, note:$n}')" "expected done + Already archived"
fi

# 4. a Space is rejected with a readable error
H3="$(post_job "$(hf_body "https://huggingface.co/spaces/gradio/hello_world" '{}')")"
st="$(wait_final "$H3" 180 | tail -1)"
err="$(field "$H3" '.error_display // .error // ""')"
if [[ "$st" == "error" && "$err" == *Spaces* ]]; then
  qc space_rejected pass "$(jq -nc --arg e "$err" '$e')" "Space rejected"
else
  qc space_rejected fail "$(jq -nc --arg s "$st" --arg e "$err" '{status:$s, error:$e}')" "expected error mentioning Spaces"
fi

# 5. a repo that does not exist reads "not found or private"
H4="$(post_job "$(hf_body "https://huggingface.co/hf-internal-testing/this-repo-does-not-exist-ap4" '{}')")"
st="$(wait_final "$H4" 300 | tail -1)"
err="$(field "$H4" '.error_display // .error // ""')"
if [[ "$st" == "error" && "$err" == "Repository not found or private" ]]; then
  qc missing_repo pass "$(jq -nc --arg e "$err" '$e')" "readable not-found"
else
  qc missing_repo fail "$(jq -nc --arg s "$st" --arg e "$err" '{status:$s, error:$e}')" "expected Repository not found or private"
fi

echo "JOBS $(jq -nc --arg h1 "$H1" --arg h2 "$H2" --arg h3 "$H3" --arg h4 "$H4" '{H1:$h1,H2:$h2,H3:$h3,H4:$h4}')"
finish
