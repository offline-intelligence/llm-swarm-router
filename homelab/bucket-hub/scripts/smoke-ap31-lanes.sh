#!/usr/bin/env bash
# AP-3.1 acceptance (§T6 step 2, adversarial order): a torrent queued *behind* repo jobs
# must still be claimed and keep progressing while a long clone holds the repo slot.
#
# Run from the Mac after AP-3.1 is deployed to both hosts. Needs curl + jq.
#   TORRENT_URL  magnet: or https://…/.torrent of a small, well-seeded legal torrent
#   DRIVE_ID     Hub drive id for the torrent (from GET /api/library)
#   FOLDER_ID    Hub folder id under that drive (the torrents/ inbox)
# Optional: HUB (default http://100.85.42.0:3000), LONG_REPO (default git/git),
#           WATCH_S (default 180), QC_OUT (default /tmp/ap31-smoke-qc.json),
#           R1_WAIT_S (default 150: longer than one HUB_REPO_DEFER_S back-off of 120 s)
#
# Machine output (docs/pm/PM-CURSOR-PROTOCOL.md): one line per check on stdout,
#   QC {"id":"smoke.<check>","status":"pass|fail|skip","value":…,"evidence":"…"}
# and a JSON array of the same objects in $QC_OUT. Exit 0 only if every check passed.
set -uo pipefail

HUB="${HUB:-http://100.85.42.0:3000}"
LONG_REPO="${LONG_REPO:-git/git}"
WATCH_S="${WATCH_S:-180}"
R1_WAIT_S="${R1_WAIT_S:-150}"
QC_OUT="${QC_OUT:-/tmp/ap31-smoke-qc.json}"
: "${TORRENT_URL:?set TORRENT_URL}" "${DRIVE_ID:?set DRIVE_ID}" "${FOLDER_ID:?set FOLDER_ID}"
command -v jq >/dev/null || { echo "jq required" >&2; exit 2; }

CHECKS=(precheck r1_running torrent_claimed_60s torrent_bytes_rise repos_drain readme_excerpt)
echo '[]' > "$QC_OUT"
qc() {  # qc <check> <pass|fail|skip> <value-json> <evidence>
  local obj
  obj="$(jq -nc --arg id "smoke.$1" --arg s "$2" --argjson v "$3" --arg e "$4" \
    '{id:$id, status:$s, value:$v, evidence:$e}')"
  echo "QC $obj"
  jq --argjson o "$obj" '. + [$o]' "$QC_OUT" > "$QC_OUT.tmp" && mv "$QC_OUT.tmp" "$QC_OUT"
}
finish() {  # mark every check not yet reported as skip, print summary, exit
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

repo_body() {
  jq -nc --arg r "$1" --argjson mb "$2" \
    '{kind:"github_repo", url:("https://github.com/"+$r), title:$r, source:"manual",
      tags:["github","ap31-smoke"], options:{refresh:true, max_size_mb:$mb}}'
}

# 1. precheck: repo lane idle
lane="$(api "$HUB/api/repo-lane")" || { qc precheck fail null "GET /api/repo-lane failed"; finish; }
active="$(echo "$lane" | jq -r .active_repo)"
if [[ "$active" != "0" ]]; then
  qc precheck fail "$active" "active_repo must be 0; dismiss running repo jobs first"; finish
fi
qc precheck pass "$(echo "$lane" | jq -c '{slot_repo, active_repo}')" "repo lane idle"

# 2. long clone holds the repo slot
R1="$(post_job "$(repo_body "$LONG_REPO" 1024)")"
[[ -n "$R1" ]] || { qc r1_running fail null "enqueue $LONG_REPO failed"; finish; }
st=""
deferred=""
r1_start=$(date +%s)
while (( $(date +%s) - r1_start < R1_WAIT_S )); do
  j1="$(job "$R1")" || j1='{}'
  st="$(echo "$j1" | jq -r '.status // ""')"
  note="$(echo "$j1" | jq -r '.progress.note // ""')"
  # Keep the first TNAS defer note as evidence; the job is retried after the back-off.
  [[ -z "$deferred" && "$note" == TNAS\ offline* ]] && deferred="$note"
  [[ "$st" == "running" || "$st" == "done" || "$st" == "error" ]] && break
  sleep 2
done
r1_s=$(( $(date +%s) - r1_start ))
if [[ "$st" != "running" ]]; then
  qc r1_running fail "$(jq -nc --arg s "$st" --arg j "$R1" --arg d "$deferred" --argjson t "$r1_s" \
    '{job:$j, status:$s, waited_s:$t, tnas_defer:$d}')" \
    "R1 not running after ${R1_WAIT_S}s (done = repo too small, pick a bigger LONG_REPO)"; finish
fi
qc r1_running pass "$(jq -nc --arg j "$R1" --arg r "$LONG_REPO" --arg d "$deferred" --argjson t "$r1_s" \
  '{job:$j, repo:$r, waited_s:$t, tnas_defer:$d}')" "R1 running"

# 3. two repo jobs queued AHEAD of the torrent, then the torrent
R2="$(post_job "$(repo_body octocat/Spoon-Knife 64)")"
R3="$(post_job "$(repo_body octocat/Hello-World 64)")"
T1="$(post_job "$(jq -nc --arg u "$TORRENT_URL" --arg d "$DRIVE_ID" --arg f "$FOLDER_ID" \
  '{url:$u, title:"ap31-smoke torrent", drive_id:$d, folder_id:$f, tags:["ap31-smoke"]}')")"
echo "JOBS $(jq -nc --arg r1 "$R1" --arg r2 "$R2" --arg r3 "$R3" --arg t1 "$T1" '{R1:$r1,R2:$r2,R3:$r3,T1:$t1}')"
[[ -n "$R2" && -n "$R3" && -n "$T1" ]] || { qc torrent_claimed_60s fail null "enqueue failed"; finish; }

# 4. watch: torrent claimed <= 60s and bytes rise while R1 is still running
start=$(date +%s); claimed_at=""; last_bytes=0; rose_during_r1=0; t_status=""
while (( $(date +%s) - start < WATCH_S )); do
  now=$(( $(date +%s) - start ))
  s1="$(field "$R1" .status)"; s2="$(field "$R2" .status)"; s3="$(field "$R3" .status)"
  tj="$(job "$T1")"; t_status="$(echo "$tj" | jq -r .status)"
  b="$(echo "$tj" | jq -r '(.progress.completed // 0) | tonumber? // 0')"
  echo "TICK $(jq -nc --argjson t "$now" --arg r1 "$s1" --arg r2 "$s2" --arg r3 "$s3" --arg t1 "$t_status" --argjson b "$b" \
    '{t:$t, R1:$r1, R2:$r2, R3:$r3, T1:$t1, t1_bytes:$b}')"
  if [[ "$t_status" == "error" ]]; then
    qc torrent_claimed_60s fail "$(echo "$tj" | jq -c '{status, error_display}')" \
      "torrent errored; likely bad TORRENT_URL, not an AP-3.1 failure: re-run with another"; finish
  fi
  [[ -z "$claimed_at" && "$t_status" != "queued" ]] && claimed_at="$now"
  if [[ "$s1" == "running" && "$b" -gt "$last_bytes" && "$last_bytes" -gt 0 ]]; then rose_during_r1=1; fi
  last_bytes="$b"
  sleep 10
done
if [[ -n "$claimed_at" && "$claimed_at" -le 60 ]]; then
  qc torrent_claimed_60s pass "$claimed_at" "torrent left queued at ${claimed_at}s"
else
  qc torrent_claimed_60s fail "$(jq -nc --arg c "${claimed_at:-never}" '$c')" "lane-blind claim still live?"
fi
if [[ "$rose_during_r1" == 1 || "$t_status" == "done" ]]; then
  qc torrent_bytes_rise pass "$last_bytes" "completed bytes rose while R1 running"
else
  qc torrent_bytes_rise fail "$last_bytes" "bytes flat while R1 running"
fi

# 5. repo jobs drain; Hello-World has a README excerpt
for _ in $(seq 1 90); do
  n=0
  for j in "$R1" "$R2" "$R3"; do s="$(field "$j" .status)"; [[ "$s" == "done" || "$s" == "error" ]] && n=$((n+1)); done
  (( n == 3 )) && break
  sleep 10
done
repos="$(for j in "$R1" "$R2" "$R3"; do job "$j" | jq -c '{id, title, status, note: .progress.note, started_at, finished_at, download_dir, error_display}'; done | jq -sc .)"
if [[ "$(echo "$repos" | jq '[.[] | select(.status == "done")] | length')" == 3 ]]; then
  qc repos_drain pass "$repos" "R1-R3 done"
else
  qc repos_drain fail "$repos" "not all repo jobs done"
fi
excerpt="$(field "$R3" '.index_entry.readme_excerpt // ""')"
dl="$(field "$R3" '.download_dir // ""')"
s3="$(field "$R3" .status)"
if [[ "$s3" != "done" ]]; then
  qc readme_excerpt fail "$(jq -nc --arg s "$s3" '{R3_status:$s}')" "R3 (Hello-World) not done, README not testable; see smoke.repos_drain"
elif [[ -n "$excerpt" ]]; then
  qc readme_excerpt pass "$(jq -nc --arg e "${excerpt:0:60}" --arg d "$dl" '{excerpt:$e, download_dir:$d}')" "Hello-World readme_excerpt non-empty"
else
  qc readme_excerpt fail "$(jq -nc --arg d "$dl" '{download_dir:$d}')" "empty readme_excerpt (archiver image still :1?)"
fi
echo "NEXT ssh ai-server-ts 'ls -la /mnt/tnas/repo-archive/$dl/'   # tnas_readme_file check"
echo "NEXT cancel or dismiss torrent $T1 in the Hub UI"
finish
