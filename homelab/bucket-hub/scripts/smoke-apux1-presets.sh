#!/usr/bin/env bash
# AP-UX-1 acceptance: download presets and segments. No real downloads.
#
#   PHASE=before ./scripts/smoke-apux1-presets.sh   # BEFORE deploying: snapshot existing connections + jobs
#   (deploy [pi] + [gateway], restart hub-form.service)
#   PHASE=after  ./scripts/smoke-apux1-presets.sh   # compare snapshot, then R1–R4
#
# R0  Sonarr/Radarr download clients, remote path mappings, root folders and Jellyfin
#     library paths are identical before and after (read-only; API keys stay on ai-server).
# R0b queued/running jobs keep their destination_path.
# R1  GET /api/presets: every preset available, or a reason naming a drive.
# R2  POST /api/presets/resolve for 5 URLs gives the expected presets.
# R3  hf_repo preset for the tiny test model ends "done" (already archived, no download).
# R4  manual_path job → destination_source "manual"; then cancelled.
#
# curl + jq on the Mac; ssh ai-server-ts for R0. Optional: HUB, STATE_DIR, QC_OUT, R3_WAIT_S (600).
# Machine output (docs/pm/PM-CURSOR-PROTOCOL.md): QC {...} lines + JSON array in $QC_OUT.
set -uo pipefail

HUB="${HUB:-http://100.85.42.0:3000}"
PHASE="${PHASE:-}"
STATE_DIR="${STATE_DIR:-/tmp/apux1-smoke}"
QC_OUT="${QC_OUT:-/tmp/apux1-qc-${PHASE:-x}.json}"
WORKER_HOST="${WORKER_HOST:-ai-server-ts}"
command -v jq >/dev/null || { echo "jq required" >&2; exit 2; }
[[ "$PHASE" == before || "$PHASE" == after ]] || { echo "PHASE must be before or after" >&2; exit 2; }
mkdir -p "$STATE_DIR"
if [[ "$PHASE" == before ]]; then CHECKS=(r0_snapshot r0b_snapshot); else CHECKS=(r0_connections r0b_jobs r1_presets r2_resolve r3_hf_preset r4_manual); fi
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
  echo "QC_SUMMARY $(jq -c --arg f "$QC_OUT" \
    '{total: length, pass: ([.[]|select(.status=="pass")]|length), fail: ([.[]|select(.status=="fail")]|length), skip: ([.[]|select(.status=="skip")]|length), file: $f}' "$QC_OUT")"
  [[ "$(jq '[.[] | select(.status != "pass")] | length' "$QC_OUT")" == 0 ]] && exit 0 || exit 1
}
api() { curl -fsS --max-time 20 "$@"; }

# Read-only snapshot of the *arr / Jellyfin paths. Runs on ai-server; keys are read from
# hub-worker.env inside python and sent as headers, never printed or put in argv.
connections_snapshot() {
  ssh "$WORKER_HOST" 'python3 - ~/homelab/scripts/hub-worker.env' <<'PY' 2>/dev/null
import json, sys, urllib.request
env = {}
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k] = v.strip().strip('"').strip("'")
def get(url, headers):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception as exc:
        return {"error": type(exc).__name__}
def keep(fields):
    return sorted(
        (f.get("name"), f.get("value")) for f in fields or []
        if any(w in str(f.get("name", "")).lower() for w in ("dir", "path", "folder", "category"))
    )
out = {}
for app, port in (("sonarr", 8989), ("radarr", 7878)):
    base = env.get(f"{app.upper()}_URL", f"http://127.0.0.1:{port}").rstrip("/")
    hdr = {"X-Api-Key": env.get(f"{app.upper()}_API_KEY", "")}
    clients = get(f"{base}/api/v3/downloadclient", hdr)
    out[app] = {
        "download_clients": sorted(
            [{"name": c.get("name"), "impl": c.get("implementation"), "enable": c.get("enable"), "paths": keep(c.get("fields"))}
             for c in clients] if isinstance(clients, list) else [clients], key=lambda c: str(c.get("name"))),
        "remote_path_mappings": get(f"{base}/api/v3/remotepathmapping", hdr),
        "root_folders": sorted(r.get("path") for r in get(f"{base}/api/v3/rootfolder", hdr) or [] if isinstance(r, dict)),
    }
jf = env.get("JELLYFIN_URL", "http://127.0.0.1:8096").rstrip("/")
libs = get(f"{jf}/Library/VirtualFolders", {"X-Emby-Token": env.get("JELLYFIN_API_KEY", "")})
out["jellyfin"] = sorted(
    [{"name": l.get("Name"), "locations": sorted(l.get("Locations") or [])} for l in libs] if isinstance(libs, list) else [libs],
    key=lambda l: str(l.get("name")))
print(json.dumps(out, sort_keys=True))
PY
}
jobs_snapshot() {
  api "$HUB/api/jobs?limit=100" | jq -c '[.jobs[] | select(.status == "queued" or .status == "running" or .status == "claimed" or .status == "paused") | {id, destination_path}] | sort_by(.id)'
}

if [[ "$PHASE" == before ]]; then
  snap="$(connections_snapshot)"
  if [[ -n "$snap" ]] && echo "$snap" | jq -e . >/dev/null 2>&1; then
    echo "$snap" > "$STATE_DIR/connections-before.json"
    qc r0_snapshot pass "$(echo "$snap" | jq -c '{radarr: .radarr.download_clients, sonarr: .sonarr.download_clients, jellyfin}')" "saved $STATE_DIR/connections-before.json"
  else
    qc r0_snapshot fail null "could not read *arr/Jellyfin paths on $WORKER_HOST"
  fi
  if js="$(jobs_snapshot)"; then
    echo "$js" > "$STATE_DIR/jobs-before.json"
    qc r0b_snapshot pass "$(jq -nc --argjson j "$js" '{active_jobs: ($j|length)}')" "saved $STATE_DIR/jobs-before.json"
  else
    qc r0b_snapshot fail null "GET /api/jobs failed"
  fi
  finish
fi

# ---- PHASE=after ------------------------------------------------------------
if [[ -f "$STATE_DIR/connections-before.json" ]]; then
  after="$(connections_snapshot)"
  if [[ -n "$after" ]] && diff <(jq -S . "$STATE_DIR/connections-before.json") <(echo "$after" | jq -S .) >"$STATE_DIR/connections.diff"; then
    qc r0_connections pass "$(echo "$after" | jq -c '{radarr_clients: .radarr.download_clients, sonarr_clients: .sonarr.download_clients}')" "before = after"
  else
    qc r0_connections fail "$(jq -Rs . < "$STATE_DIR/connections.diff")" "Sonarr/Radarr/Jellyfin paths changed (or unreadable) since PHASE=before"
  fi
else
  qc r0_connections fail null "run PHASE=before first"
fi

if [[ -f "$STATE_DIR/jobs-before.json" ]]; then
  now="$(api "$HUB/api/jobs?limit=100" | jq -c '[.jobs[] | {id, destination_path}]')"
  changed="$(jq -nc --slurpfile b "$STATE_DIR/jobs-before.json" --argjson n "$now" \
    '[$b[0][] as $o | ($n[] | select(.id == $o.id)) as $x | select($x.destination_path != $o.destination_path) | {id: $o.id, before: $o.destination_path, after: $x.destination_path}]')"
  if [[ "$(echo "$changed" | jq length)" == 0 ]]; then
    qc r0b_jobs pass "$(jq -nc --slurpfile b "$STATE_DIR/jobs-before.json" '{checked: ($b[0]|length)}')" "no destination_path changed"
  else
    qc r0b_jobs fail "$changed" "existing jobs changed destination"
  fi
else
  qc r0b_jobs fail null "run PHASE=before first"
fi

if p="$(api "$HUB/api/presets")"; then
  ids="$(echo "$p" | jq -c '[.presets[].id] | sort')"
  bad="$(echo "$p" | jq -c '[.presets[] | select(.available != true and ((.reason // "") | test("mounted|library|folder") | not)) | .id]')"
  summary="$(echo "$p" | jq -c '[.presets[] | {id, available, saves_to, path: (.destination.path // .destination.subdir // null), reason}]')"
  # r2: TV and film must land where Sonarr/Radarr import from (r1 F2 sent tv to TNAS inbox).
  pinned="$(echo "$p" | jq -c '[.presets[] | select(.available == true)
    | select((.id == "tv" or .id == "film") and .destination.path != "/mnt/external/movies/torrents"
      or .id == "website" and ((.destination.folder_id // "") | test("website_backups|nas_staging") | not)) | .id]')"
  if [[ "$ids" == '["file","film","github_repo","hf_files","hf_repo","tv","video","website"]' && "$bad" == "[]" && "$pinned" == "[]" ]]; then
    qc r1_presets pass "$summary" "8 presets; unavailable ones name a drive or folder; tv/film -> /mnt/external/movies/torrents"
  else
    qc r1_presets fail "$summary" "ids=$ids unexplained=$bad wrong_destination=$pinned"
  fi
else
  qc r1_presets fail null "GET /api/presets failed (old app.py?)"
fi

r2_fail=0; r2=()
while IFS='|' read -r url want; do
  got="$(api -X POST "$HUB/api/presets/resolve" -H 'Content-Type: application/json' -d "$(jq -nc --arg u "$url" '{url:$u}')" | jq -r '.preset // "ERR"')"
  r2+=("$(jq -nc --arg u "$url" --arg w "$want" --arg g "$got" '{url:$u, want:$w, got:$g}')")
  [[ "$got" == "$want" ]] || r2_fail=1
done <<'EOF'
https://github.com/octocat/Hello-World|github_repo
https://huggingface.co/hf-internal-testing/tiny-random-gpt2|hf_repo
magnet:?xt=urn:btih:0000000000000000000000000000000000000000&dn=apux1-smoke|tv
https://www.youtube.com/watch?v=aqz-KE-bpKQ|video
https://example.com/robots.txt|file
EOF
r2json="$(printf '%s\n' "${r2[@]}" | jq -sc .)"
if [[ "$r2_fail" == 0 ]]; then qc r2_resolve pass "$r2json" "5/5"; else qc r2_resolve fail "$r2json" "mismatch"; fi

JOBS=()
r3="$(api -X POST "$HUB/api/jobs" -H 'Content-Type: application/json' \
  -d '{"url":"https://huggingface.co/hf-internal-testing/tiny-random-gpt2","preset":"hf_repo","title":"apux1-smoke","tags":["apux1-smoke"],"options":{"max_size_mb":500}}')"
r3id="$(echo "$r3" | jq -r '.job.id // empty')"
if [[ -n "$r3id" ]]; then
  JOBS+=("$r3id")
  st=""; t0=$(date +%s)
  while (( $(date +%s) - t0 < ${R3_WAIT_S:-600} )); do
    st="$(api "$HUB/api/jobs/$r3id" | jq -r .status)"
    [[ "$st" == done || "$st" == error ]] && break
    sleep 10
  done
  v="$(api "$HUB/api/jobs/$r3id" | jq -c '{id, status, kind, preset, segment, destination_source, note: .progress.note}')"
  if [[ "$st" == done ]] && echo "$v" | jq -e '.preset == "hf_repo" and .segment == "repo" and .kind == "huggingface_repo"' >/dev/null; then
    qc r3_hf_preset pass "$v" "preset job finished"
  else
    qc r3_hf_preset fail "$v" "expected done with preset hf_repo"
  fi
else
  qc r3_hf_preset fail "$(echo "$r3" | jq -c . 2>/dev/null || echo null)" "POST /api/jobs failed"
fi

tvdest="$(api "$HUB/api/presets" | jq -c '.presets[] | select(.id == "tv") | .destination')"
if [[ "$tvdest" != "null" && -n "$tvdest" ]]; then
  body="$(jq -nc --argjson d "$tvdest" '{url:"magnet:?xt=urn:btih:0000000000000000000000000000000000000000&dn=apux1-smoke-manual",
    preset:"tv", manual_path:true, drive_id:$d.drive_id, folder_id:$d.folder_id, title:"apux1-smoke-manual", tags:["apux1-smoke"]}')"
  r4id="$(api -X POST "$HUB/api/jobs" -H 'Content-Type: application/json' -d "$body" | jq -r '.job.id // empty')"
  if [[ -n "$r4id" ]]; then
    JOBS+=("$r4id")
    v="$(api "$HUB/api/jobs/$r4id" | jq -c '{id, destination_source, preset, segment, destination_path}')"
    api -X POST "$HUB/api/jobs/$r4id/cancel" -H 'Content-Type: application/json' -d '{}' >/dev/null || true
    if echo "$v" | jq -e '.destination_source == "manual" and .segment == "tv"' >/dev/null; then
      qc r4_manual pass "$v" "manual job created and cancelled"
    else
      qc r4_manual fail "$v" "expected destination_source manual"
    fi
  else
    qc r4_manual fail null "POST /api/jobs (manual) failed"
  fi
else
  qc r4_manual skip null "tv preset unavailable (Expansion HDD offline)"
fi
echo "JOBS ${JOBS[*]:-}"
finish
