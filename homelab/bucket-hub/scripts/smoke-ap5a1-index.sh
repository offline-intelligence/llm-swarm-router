#!/usr/bin/env bash
# AP-5a.1 acceptance: per-download record on the Pi (journal API) and ABOUT-THIS-DOWNLOAD.md.
#
#   ./scripts/smoke-ap5a1-index.sh
#
# X1  GET /api/index/export: JSONL, X-Index-Cursor = byte size; a second call with that cursor is empty.
# X2  GET /api/index/search?q=Hello-World finds the GitHub archive record (from AP-3 smokes).
# X3  GET /api/index/{id}/card for that record: What / Where / Why / When headings.
# X4  PATCH a note on the HF smoke record (tiny-random-gpt2) → visible in the record and the export tail.
# X5  GET /api/index/sources?kind=huggingface_repo includes the HF smoke repo.
# X6  Re-archive the HF smoke model (options.refresh) → done; ABOUT-THIS-DOWNLOAD.md beside it on the
#     worker, containing the title and the X4 note is NOT required (note came later; title + source are).
# X7  Back-fill dry run on the Pi: counts only, journal size unchanged.
#
# Optional: HUB, PI_HOST (stackrise-pi), WORKER_HOST (ai-server-ts), ARCHIVE_ROOT (/mnt/tnas/repo-archive),
# PI_JOBS_DIR (~/homelab/data/hub-jobs), PI_APP_DIR (~/homelab/hub-form), X6_WAIT_S (600), QC_OUT.
set -uo pipefail

HUB="${HUB:-http://100.85.42.0:3000}"
PI_HOST="${PI_HOST:-stackrise-pi}"
WORKER_HOST="${WORKER_HOST:-ai-server-ts}"
ARCHIVE_ROOT="${ARCHIVE_ROOT:-/mnt/tnas/repo-archive}"
PI_JOBS_DIR="${PI_JOBS_DIR:-~/homelab/data/hub-jobs}"
PI_APP_DIR="${PI_APP_DIR:-~/homelab/hub-form}"
QC_OUT="${QC_OUT:-/tmp/ap5a1-qc.json}"
HF_REPO="hf-internal-testing/tiny-random-gpt2"
CHECKS=(x1_export x2_search x3_card x4_note x5_sources x6_about_file x7_backfill_dry_run)
command -v jq >/dev/null || { echo "jq required" >&2; exit 2; }
echo '[]' > "$QC_OUT"
qc() {  # qc <check> <pass|fail|skip> <value-json> <evidence>
  local obj
  obj="$(jq -nc --arg id "smoke.$1" --arg s "$2" --argjson v "$3" --arg e "$4" '{id:$id, status:$s, value:$v, evidence:$e}')"
  echo "QC $obj"
  jq --argjson o "$obj" '. + [$o]' "$QC_OUT" > "$QC_OUT.tmp" && mv "$QC_OUT.tmp" "$QC_OUT"
}
finish() {
  local id
  for id in "${CHECKS[@]}"; do
    jq -e --arg id "smoke.$id" 'any(.[]; .id == $id)' "$QC_OUT" >/dev/null || qc "$id" skip null "not reached"
  done
  echo "QC_SUMMARY $(jq -c --arg f "$QC_OUT" '{total: length, pass: ([.[]|select(.status=="pass")]|length), fail: ([.[]|select(.status=="fail")]|length), skip: ([.[]|select(.status=="skip")]|length), file: $f}' "$QC_OUT")"
  [[ "$(jq '[.[] | select(.status != "pass")] | length' "$QC_OUT")" == 0 ]] && exit 0 || exit 1
}
api() { curl -fsS --max-time 30 "$@"; }
enc() { jq -rn --arg s "$1" '$s|@uri'; }

# X1
hdr="$(mktemp)"; body="$(mktemp)"
if curl -fsS --max-time 30 -D "$hdr" -o "$body" "$HUB/api/index/export"; then
  cur="$(awk -F': ' 'tolower($1)=="x-index-cursor"{gsub("\r","",$2); print $2}' "$hdr")"
  n="$(grep -c . "$body" || true)"
  bad="$(jq -c 'select(type != "object" or (.entry_id|not))' "$body" 2>/dev/null | head -1)"
  again="$(api "$HUB/api/index/export?since=$cur" | grep -c . || true)"
  v="$(jq -nc --arg c "$cur" --argjson n "$n" --argjson a "$again" '{cursor: ($c|tonumber? // $c), records: $n, after_cursor: $a}')"
  if [[ -n "$cur" && "$n" -gt 0 && -z "$bad" && "$again" == 0 ]]; then qc x1_export pass "$v" "JSONL + cursor"; else qc x1_export fail "$v" "bad export"; fi
else
  qc x1_export fail null "GET /api/index/export failed (old app.py?)"; finish
fi

# X2 + X3
s="$(api "$HUB/api/index/search?q=Hello-World&kind=github_repo")"
gid="$(echo "$s" | jq -r '.items[0].entry_id // empty')"
if [[ -n "$gid" ]]; then
  qc x2_search pass "$(echo "$s" | jq -c '{total, first: (.items[0] | {entry_id, title, status, segment})}')" "found GitHub archive record"
  card="$(api "$HUB/api/index/$(enc "$gid")/card")"
  heads="$(echo "$card" | grep -cE '^## (What|Where|Why|When)$' || true)"
  if [[ "$heads" == 4 ]]; then qc x3_card pass "$(jq -nc --arg t "$(echo "$card" | head -1)" '{title_line: $t, headings: 4}')" "context card"; else qc x3_card fail "$(jq -nc --argjson h "$heads" '{headings: $h}')" "missing headings"; fi
else
  qc x2_search fail "$(echo "$s" | jq -c '{total}')" "no Hello-World record (has an AP-3 smoke run on this Hub?)"
fi

# X4 + X5
h="$(api "$HUB/api/index/search?q=tiny-random-gpt2&kind=huggingface_repo")"
hid="$(echo "$h" | jq -r '.items[0].entry_id // empty')"
if [[ -n "$hid" ]]; then
  note="ap5a1 smoke note $(date +%s)"
  got="$(api -X PATCH "$HUB/api/index/$(enc "$hid")" -H 'Content-Type: application/json' -d "$(jq -nc --arg n "$note" '{user_note:$n}')" | jq -r .user_note)"
  tail_note="$(api "$HUB/api/index/export?since=$cur" | jq -r --arg id "$hid" 'select(.entry_id==$id) | .user_note')"
  v="$(jq -nc --arg id "$hid" --arg g "$got" --arg t "$tail_note" '{entry_id:$id, record:$g, export_tail:$t}')"
  if [[ "$got" == "$note" && "$tail_note" == "$note" ]]; then qc x4_note pass "$v" "note stored and exported"; else qc x4_note fail "$v" "note mismatch"; fi
  src="$(api "$HUB/api/index/sources?kind=huggingface_repo")"
  sid="$(echo "$h" | jq -r '.items[0].source_id')"
  if echo "$src" | jq -e --arg s "$sid" '.source_ids | index($s)' >/dev/null; then qc x5_sources pass "$(echo "$src" | jq -c '{count}')" "smoke repo listed"; else qc x5_sources fail "$(echo "$src" | jq -c '{count}')" "smoke repo missing"; fi
else
  qc x4_note fail null "no tiny-random-gpt2 record"
fi

# X6
job="$(api -X POST "$HUB/api/jobs" -H 'Content-Type: application/json' \
  -d "{\"url\":\"https://huggingface.co/$HF_REPO\",\"preset\":\"hf_repo\",\"title\":\"ap5a1-smoke\",\"tags\":[\"ap5a1-smoke\"],\"options\":{\"refresh\":true,\"max_size_mb\":500}}" | jq -r '.job.id // empty')"
if [[ -n "$job" ]]; then
  st=""; t0=$(date +%s)
  while (( $(date +%s) - t0 < ${X6_WAIT_S:-600} )); do
    st="$(api "$HUB/api/jobs/$job" | jq -r .status)"; [[ "$st" == done || "$st" == error ]] && break; sleep 10
  done
  dir="$(api "$HUB/api/jobs/$job" | jq -r '.download_dir // empty')"
  about="$(ssh "$WORKER_HOST" "f='$ARCHIVE_ROOT/$dir/ABOUT-THIS-DOWNLOAD.md'; test -f \"\$f\" && { head -1 \"\$f\"; grep -c '^## ' \"\$f\"; grep -c 'huggingface.co' \"\$f\"; }" 2>/dev/null | tr '\n' '|')"
  v="$(jq -nc --arg j "$job" --arg s "$st" --arg d "$dir" --arg a "$about" '{job:$j, status:$s, download_dir:$d, about:$a}')"
  if [[ "$st" == done && "$about" == "# $HF_REPO|"* ]]; then qc x6_about_file pass "$v" "ABOUT-THIS-DOWNLOAD.md beside the archive"; else qc x6_about_file fail "$v" "expected done + ABOUT file"; fi
  echo "JOBS $job"
else
  qc x6_about_file fail null "POST /api/jobs failed"
fi

# X7
before="$(ssh "$PI_HOST" "stat -c %s $PI_JOBS_DIR/download-index.jsonl" 2>/dev/null)"
dry="$(ssh "$PI_HOST" "cd $PI_APP_DIR && python3 scripts/rebuild-download-index.py --from-jobs $PI_JOBS_DIR --dry-run" 2>/dev/null | tail -1)"
after="$(ssh "$PI_HOST" "stat -c %s $PI_JOBS_DIR/download-index.jsonl" 2>/dev/null)"
if echo "$dry" | jq -e '.dry_run == true and .written == 0' >/dev/null 2>&1 && [[ "$before" == "$after" ]]; then
  qc x7_backfill_dry_run pass "$(echo "$dry" | jq -c '{jobs, done, already_indexed, skipped_not_download, to_write, by_kind}')" "dry run, journal unchanged"
else
  qc x7_backfill_dry_run fail "$(jq -nc --arg d "$dry" --arg b "$before" --arg a "$after" '{out:$d, size_before:$b, size_after:$a}')" "dry run failed or journal changed"
fi

finish
