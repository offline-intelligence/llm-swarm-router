#!/usr/bin/env bash
# AP-5a.2 acceptance: the ai-server download catalogue (hub-index) searches every drive.
#
#   ./scripts/smoke-ap5a2-catalog.sh
#
# C0  ai-server: SQLite has FTS5; hub-index active; the catalogue file is on the root SSD (df target "/").
# C1  /health: every mounted root has a full-scan time; first rebuild finished (last_rebuild set).
# C2  Catalogue search: "Hello-World" → the GitHub archive item on TNAS; SHOW (default "Office") → a tv
#     item; SHOW_FILE (default "S03E01") with scope=files → an episode file with its owning item.
# C3  A note PATCHed on the Pi reaches catalogue search within 75 s (journal tail); old note restored.
# C4  Re-archive the HF smoke model (options.refresh) → its files are in the catalogue within 60 s of
#     done (worker nudge, no full scan).
# C5  The overnight index_rebuild step run on its own (on the Pi) → counts in result_text; the Pi
#     snapshot file is rewritten.
# C6  The live overnight schedule has "Rebuild download index" just before "Sleep ai-server".
#
# Optional: HUB, PI_HOST (stackrise-pi), WORKER_HOST (ai-server-ts), PI_JOBS_DIR, PI_APP_DIR, SHOW,
# SHOW_FILE, C4_WAIT_S (600), QC_OUT.
set -uo pipefail

HUB="${HUB:-http://100.85.42.0:3000}"
PI_HOST="${PI_HOST:-stackrise-pi}"
WORKER_HOST="${WORKER_HOST:-ai-server-ts}"
PI_JOBS_DIR="${PI_JOBS_DIR:-~/homelab/data/hub-jobs}"
PI_APP_DIR="${PI_APP_DIR:-~/homelab/hub-form}"
SHOW="${SHOW:-Office}"
SHOW_FILE="${SHOW_FILE:-S03E01}"
QC_OUT="${QC_OUT:-/tmp/ap5a2-qc.json}"
HF_REPO="hf-internal-testing/tiny-random-gpt2"
CHECKS=(c0_prereqs c1_health c2_search c3_note_tail c4_nudge c5_overnight_step c6_schedule)
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
# catalogue GET on ai-server (hub-index listens there; the Pi proxy arrives in AP-5b)
cat_get() { ssh "$WORKER_HOST" "curl -fsS --max-time 30 'http://127.0.0.1:3031$1'" 2>/dev/null; }

# C0
pre="$(ssh "$WORKER_HOST" 'python3 -c "import sqlite3; c=sqlite3.connect(\":memory:\"); c.execute(\"create virtual table t using fts5(a)\"); print(\"fts5\")" 2>&1 | tail -1;
  systemctl --user is-active hub-index 2>&1 | head -1;
  df --output=target ~/homelab/data/hub-index 2>/dev/null | tail -1' 2>/dev/null | tr '\n' '|')"
IFS='|' read -r fts active target _ <<<"$pre"
v="$(jq -nc --arg f "$fts" --arg a "$active" --arg t "$target" '{fts5:$f, service:$a, db_mount:$t}')"
if [[ "$fts" == fts5 && "$active" == active && "$target" == / ]]; then qc c0_prereqs pass "$v" "ai-server prereqs"; else qc c0_prereqs fail "$v" "need fts5, hub-index active, catalogue on /"; finish; fi

# C1 (first start runs a full rebuild in the background: wait for it)
h=""; t0=$(date +%s)
while (( $(date +%s) - t0 < 1800 )); do
  h="$(cat_get /health)"; [[ "$(echo "$h" | jq -r '.last_rebuild // empty' 2>/dev/null)" != "" ]] && break; sleep 20
done
v="$(echo "$h" | jq -c '{items, files, last_rebuild, last_error, db_bytes, roots: [.roots[] | {root_id, mounted, last_full_scan, last_scan_complete, files}]}' 2>/dev/null || echo null)"
if echo "$h" | jq -e '.last_rebuild and ([.roots[] | select(.mounted) | select(.last_full_scan|not)] | length == 0) and ([.roots[] | select(.mounted)] | length > 0)' >/dev/null 2>&1; then
  qc c1_health pass "$v" "every mounted root scanned"
else
  qc c1_health fail "$v" "no rebuild yet, or a mounted root without a scan"
fi

# C2
gh="$(cat_get "/search?q=Hello-World&kind=github_repo")"
tv="$(cat_get "/search?q=$(enc "$SHOW")&kind=tv")"
fl="$(cat_get "/search?q=$(enc "$SHOW_FILE")&scope=files")"
v="$(jq -nc --argjson g "${gh:-null}" --argjson t "${tv:-null}" --argjson f "${fl:-null}" \
  '{github: ($g.items[0] // null | if . then {item_id, where, status} else null end), tv: ($t.items[0] // null | if . then {item_id, where, file_count} else null end), file: ($f.files[0] // null | if . then {where, item: .item.item_id} else null end)}' 2>/dev/null || echo null)"
if echo "$v" | jq -e '(.github.where | startswith("TNAS")) and (.tv.file_count > 0) and (.file.item != null)' >/dev/null 2>&1; then
  qc c2_search pass "$v" "repo, show and episode found"
else
  qc c2_search fail "$v" "expected a TNAS repo item, a tv item and an episode file"
fi

# C3
gid="$(api "$HUB/api/index/search?q=Hello-World&kind=github_repo" | jq -r '.items[0].entry_id // empty')"
if [[ -n "$gid" ]]; then
  old="$(api "$HUB/api/index/$(enc "$gid")" | jq -r '.user_note // ""')"
  word="zebracorn$(date +%s)"
  api -X PATCH "$HUB/api/index/$(enc "$gid")" -H 'Content-Type: application/json' -d "$(jq -nc --arg n "ap5a2 smoke $word" '{user_note:$n}')" >/dev/null
  t0=$(date +%s); found=""
  while (( $(date +%s) - t0 < 75 )); do
    found="$(cat_get "/search?q=$word" | jq -r '.items[0].item_id // empty')"; [[ -n "$found" ]] && break; sleep 5
  done
  secs=$(( $(date +%s) - t0 ))
  api -X PATCH "$HUB/api/index/$(enc "$gid")" -H 'Content-Type: application/json' -d "$(jq -nc --arg n "$old" '{user_note:$n}')" >/dev/null
  v="$(jq -nc --arg id "$gid" --arg f "$found" --argjson s "$secs" '{entry_id:$id, found:$f, secs:$s, old_note_restored:true}')"
  if [[ "$found" == "$gid" ]]; then qc c3_note_tail pass "$v" "note searchable via journal tail"; else qc c3_note_tail fail "$v" "note not in catalogue within 75 s"; fi
else
  qc c3_note_tail fail null "no Hello-World record on the Pi"
fi

# C4
start_iso="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; start_s=$(date +%s)
job="$(api -X POST "$HUB/api/jobs" -H 'Content-Type: application/json' \
  -d "{\"url\":\"https://huggingface.co/$HF_REPO\",\"preset\":\"hf_repo\",\"title\":\"ap5a2-smoke\",\"tags\":[\"ap5a2-smoke\"],\"options\":{\"refresh\":true,\"max_size_mb\":500}}" | jq -r '.job.id // empty')"
if [[ -n "$job" ]]; then
  st=""; t0=$(date +%s)
  while (( $(date +%s) - t0 < ${C4_WAIT_S:-600} )); do
    st="$(api "$HUB/api/jobs/$job" | jq -r .status)"; [[ "$st" == done || "$st" == error ]] && break; sleep 5
  done
  done_s=$(date +%s); fresh=""; item=""
  hid="$(api "$HUB/api/index/search?q=tiny-random-gpt2&kind=huggingface_repo" | jq -r '.items[0].entry_id // empty')"
  while [[ "$st" == done ]] && (( $(date +%s) - done_s < 60 )); do
    item="$(cat_get "/item/$(enc "$hid")")"
    fresh="$(echo "$item" | jq -r --argjson t "$start_s" '[.files[] | select(.mtime >= ($t - 5))] | length' 2>/dev/null)"
    [[ "${fresh:-0}" -gt 0 ]] && break; sleep 3
  done
  lag=$(( $(date +%s) - done_s ))
  v="$(jq -nc --arg j "$job" --arg s "$st" --arg id "$hid" --arg f "${fresh:-0}" --argjson l "$lag" --arg at "$start_iso" '{job:$j, status:$s, entry_id:$id, fresh_files:($f|tonumber? // 0), secs_after_done:$l, started:$at}')"
  if [[ "$st" == done && "${fresh:-0}" -gt 0 ]]; then qc c4_nudge pass "$v" "new files searchable after the worker nudge"; else qc c4_nudge fail "$v" "files not in the catalogue within 60 s of done"; fi
  echo "JOBS $job"
else
  qc c4_nudge fail null "POST /api/jobs failed"
fi

# C5
snap_before="$(ssh "$PI_HOST" "stat -c %Y $PI_JOBS_DIR/index-snapshot.jsonl.gz 2>/dev/null || echo 0")"
step="$(ssh "$PI_HOST" "cd $PI_APP_DIR && JOBS_DIR=$PI_JOBS_DIR python3 - <<'PY'
import importlib.util, json
spec = importlib.util.spec_from_file_location('ovr', 'scripts/overnight-run.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
step = {'id': 'index-rebuild', 'type': 'index_rebuild', 'label': 'Rebuild download index', 'timeout_min': 30}
try:
    e = m.run_step(step, False, '')
    print(json.dumps({'ok': e.get('ok'), 'result_text': e.get('result_text'), 'result': {k: (e.get('result') or {}).get(k) for k in ('new','changed','missing','deleted','items','files','secs','snapshot')}}))
except Exception as exc:
    print(json.dumps({'ok': False, 'error': str(exc)[:300]}))
PY" 2>/dev/null | tail -1)"
snap_after="$(ssh "$PI_HOST" "stat -c %Y $PI_JOBS_DIR/index-snapshot.jsonl.gz 2>/dev/null || echo 0")"
v="$(jq -nc --argjson s "${step:-null}" --arg b "$snap_before" --arg a "$snap_after" '{step:$s, snapshot_mtime_before:($b|tonumber), snapshot_mtime_after:($a|tonumber)}' 2>/dev/null || echo null)"
if echo "$v" | jq -e '.step.ok and (.step.result_text | test("^[0-9]+ new, [0-9]+ changed, [0-9]+ missing, [0-9]+ deleted$")) and (.snapshot_mtime_after > .snapshot_mtime_before)' >/dev/null 2>&1; then
  qc c5_overnight_step pass "$v" "step ran over ssh; snapshot rewritten"
else
  qc c5_overnight_step fail "$v" "step failed, odd result_text, or snapshot not pushed"
fi

# C6
sched="$(api "$HUB/api/overnight/schedule")"
order="$(echo "$sched" | jq -c '[.schedule.steps[] | select(.enabled != false) | .type]')"
if echo "$order" | jq -e 'index("index_rebuild") != null and (index("index_rebuild") + 1) == index("machine_sleep")' >/dev/null 2>&1; then
  qc c6_schedule pass "$order" "rebuild runs before ai-server sleeps"
else
  qc c6_schedule fail "$order" "index_rebuild missing or not just before machine_sleep"
fi

finish
