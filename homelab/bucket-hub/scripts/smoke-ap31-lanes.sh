#!/usr/bin/env bash
# AP-3.1 acceptance (§T6 step 2, adversarial order): a torrent queued *behind* repo jobs
# must still be claimed and keep progressing while a long clone holds the repo slot.
#
# Run from the Mac after AP-3.1 is deployed to both hosts. Needs curl + jq.
#   TORRENT_URL  magnet: or https://…/.torrent of a small, well-seeded legal torrent
#   DRIVE_ID     Hub drive id for the torrent (e.g. the Expansion HDD id from GET /api/library)
#   FOLDER_ID    Hub folder id under that drive (the torrents/ inbox)
# Optional: HUB (default http://100.85.42.0:3000), LONG_REPO (default git/git), WATCH_S (default 180)
set -euo pipefail

HUB="${HUB:-http://100.85.42.0:3000}"
LONG_REPO="${LONG_REPO:-git/git}"
WATCH_S="${WATCH_S:-180}"
: "${TORRENT_URL:?set TORRENT_URL}" "${DRIVE_ID:?set DRIVE_ID}" "${FOLDER_ID:?set FOLDER_ID}"

post_job() { curl -fsS -X POST "$HUB/api/jobs" -H 'Content-Type: application/json' -d "$1" | jq -r '.job.id'; }
job() { curl -fsS "$HUB/api/jobs/$1"; }
field() { job "$1" | jq -r "$2"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

echo "== precheck"
lane="$(curl -fsS "$HUB/api/repo-lane")"
echo "$lane" | jq -c '{slot_repo, active_repo, archive_root}'
[[ "$(echo "$lane" | jq -r .active_repo)" == "0" ]] || fail "repo lane busy; dismiss running repo jobs first"

repo_body() {
  jq -nc --arg r "$1" --argjson mb "$2" \
    '{kind:"github_repo", url:("https://github.com/"+$r), title:$r, source:"manual",
      tags:["github","ap31-smoke"], options:{refresh:true, max_size_mb:$mb}}'
}

echo "== 1. long clone to hold the repo slot: $LONG_REPO"
R1="$(post_job "$(repo_body "$LONG_REPO" 1024)")"
for _ in $(seq 1 30); do
  st="$(field "$R1" .status)"; [[ "$st" == "running" ]] && break
  [[ "$st" == "done" || "$st" == "error" ]] && fail "R1 finished before the test could start ($st); pick a bigger LONG_REPO"
  sleep 2
done
[[ "$(field "$R1" .status)" == "running" ]] || fail "R1 never started"

echo "== 2. two repo jobs queued AHEAD of the torrent"
R2="$(post_job "$(repo_body octocat/Spoon-Knife 64)")"
R3="$(post_job "$(repo_body octocat/Hello-World 64)")"
echo "== 3. torrent queued last"
T1="$(post_job "$(jq -nc --arg u "$TORRENT_URL" --arg d "$DRIVE_ID" --arg f "$FOLDER_ID" \
  '{url:$u, title:"ap31-smoke torrent", drive_id:$d, folder_id:$f, tags:["ap31-smoke"]}')")"
echo "R1=$R1 R2=$R2 R3=$R3 T1=$T1"

echo "== 4. watch ${WATCH_S}s (pass: torrent claimed <60s and bytes rise while R1 runs)"
printf '%-6s %-9s %-9s %-9s %-9s %s\n' t R1 R2 R3 T1 t1_bytes
start=$(date +%s); claimed_at=""; first_bytes=""; last_bytes=0; rose_during_r1=0
while (( $(date +%s) - start < WATCH_S )); do
  now=$(( $(date +%s) - start ))
  s1="$(field "$R1" .status)"; s2="$(field "$R2" .status)"; s3="$(field "$R3" .status)"
  tj="$(job "$T1")"; st="$(echo "$tj" | jq -r .status)"
  b="$(echo "$tj" | jq -r '(.progress.completed // 0) | tonumber? // 0')"
  printf '%-6s %-9s %-9s %-9s %-9s %s\n' "${now}s" "$s1" "$s2" "$s3" "$st" "$b"
  [[ "$st" == "error" ]] && fail "torrent errored: $(echo "$tj" | jq -r .error_display) (bad TORRENT_URL? re-run with another)"
  [[ -z "$claimed_at" && "$st" != "queued" ]] && claimed_at="$now"
  [[ -z "$first_bytes" && "$b" -gt 0 ]] && first_bytes="$b"
  if [[ "$s1" == "running" && "$b" -gt "$last_bytes" && "$last_bytes" -gt 0 ]]; then rose_during_r1=1; fi
  last_bytes="$b"
  sleep 10
done

[[ -n "$claimed_at" && "$claimed_at" -le 60 ]] || fail "torrent not claimed within 60s (claimed_at=${claimed_at:-never}): lane-blind claim still live?"
[[ "$rose_during_r1" == 1 || "$(field "$T1" .status)" == "done" ]] \
  || fail "torrent bytes did not rise while the clone ran"
echo "PASS torrent: claimed at ${claimed_at}s, bytes rose while repo slot was busy"

echo "== 5. let repo jobs drain, then check README.md on Hello-World"
for _ in $(seq 1 90); do
  done_n=0
  for j in "$R1" "$R2" "$R3"; do s="$(field "$j" .status)"; [[ "$s" == "done" || "$s" == "error" ]] && done_n=$((done_n+1)); done
  (( done_n == 3 )) && break
  sleep 10
done
for j in "$R1" "$R2" "$R3"; do echo "$j $(job "$j" | jq -c '{title, status, note: .progress.note, download_dir, err: .error_display}')"; done
[[ "$(field "$R3" .status)" == "done" ]] || fail "Hello-World job not done"
excerpt="$(field "$R3" '.index_entry.readme_excerpt // ""')"
[[ -n "$excerpt" ]] || fail "Hello-World readme_excerpt empty (archiver image still :1?)"
echo "PASS Hello-World readme_excerpt: ${excerpt:0:40}"
echo "Now on ai-server: ls -la /mnt/tnas/repo-archive/$(field "$R3" .download_dir)/  (expect README.md, repo.git/, both sidecars)"
echo "Cancel or dismiss the smoke torrent $T1 in the Hub UI when you are done."
