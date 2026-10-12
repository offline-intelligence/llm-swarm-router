#!/usr/bin/env bash
# OPS-ARR2 acceptance: the host worker reaches Sonarr/Radarr the way it does after a torrent completes.
#
#   ./scripts/smoke-ops-arr2.sh
#
# D1  Read-only paths from the worker host to Sonarr/Radarr (no API key used):
#     /ping over 127.0.0.1, the host LAN IP and the Gluetun container IP; /ping from inside the
#     Gluetun and app containers; curl present in the app image; app NetworkMode still pointing at
#     the running Gluetun container (a Gluetun restart leaves *arr on a dead namespace).
# M1  `arr_client.py --check` with hub-worker.env loaded: the worker's own transport
#     (SONARR_URL / SONARR_VIA_DOCKER, same for Radarr) answers /api/v3/system/status.
#
# Optional: WORKER_HOST (ai-server-ts), WORKER_DIR (~/homelab/scripts), QC_OUT.
set -uo pipefail

WORKER_HOST="${WORKER_HOST:-ai-server-ts}"
WORKER_DIR="${WORKER_DIR:-~/homelab/scripts}"
QC_OUT="${QC_OUT:-/tmp/ops-arr2-qc.json}"
CHECKS=(d1_paths m1_arr_check)
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

# D1: one JSON object per app. HTTP codes only; 000 = no answer.
d1="$(ssh "$WORKER_HOST" 'bash -s' <<'REMOTE'
code() { curl -s -o /dev/null -m 5 -w '%{http_code}' "$1" 2>/dev/null || true; }
lan="$(hostname -I 2>/dev/null | awk '{print $1}')"
gl_id="$(docker inspect -f '{{.Id}}' gluetun 2>/dev/null)"
gl_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' gluetun 2>/dev/null | awk '{print $1}')"
for pair in sonarr:8989 radarr:7878; do
  app="${pair%%:*}"; port="${pair##*:}"
  mode="$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$app" 2>/dev/null)"
  ns_ok=false; [[ -n "$gl_id" && "$mode" == "container:$gl_id" ]] && ns_ok=true
  # compose writes container:<id>; a stale id means the app kept a dead Gluetun namespace
  in_gl="$(docker exec gluetun wget -q -T 5 -O /dev/null "http://127.0.0.1:$port/ping" >/dev/null 2>&1 && echo 200 || echo 000)"
  in_app="$(docker exec "$app" curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$port/ping" 2>/dev/null || true)"; in_app="${in_app:-000}"
  has_curl="$(docker exec "$app" sh -c 'command -v curl >/dev/null' 2>/dev/null && echo true || echo false)"
  bind="$(docker exec "$app" sh -c "grep -o '<BindAddress>[^<]*</BindAddress>' /config/config.xml" 2>/dev/null | sed 's/<[^>]*>//g')"
  printf '{"app":"%s","host_loopback":"%s","host_lan":"%s","lan_ip":"%s","gluetun_ip":"%s","host_gluetun_ip":"%s","in_gluetun":"%s","in_app":"%s","app_has_curl":%s,"netns_current":%s,"bind_address":"%s","running":"%s"}\n' \
    "$app" "$(code "http://127.0.0.1:$port/ping")" "$( [[ -n "$lan" ]] && code "http://$lan:$port/ping" || echo n/a)" "$lan" \
    "$gl_ip" "$( [[ -n "$gl_ip" ]] && code "http://$gl_ip:$port/ping" || echo n/a)" "$in_gl" "$in_app" "$has_curl" "$ns_ok" "$bind" \
    "$(docker inspect -f '{{.State.Status}}' "$app" 2>/dev/null || echo missing)"
done
REMOTE
)"
if [[ -n "$d1" ]] && echo "$d1" | jq -se 'length == 2' >/dev/null 2>&1; then
  qc d1_paths pass "$(echo "$d1" | jq -sc .)" "read-only probes on $WORKER_HOST"
else
  qc d1_paths fail null "could not collect probes from $WORKER_HOST"
fi

# M1: the worker's transport, with the worker's env. arr_client never prints the key.
m1="$(ssh "$WORKER_HOST" "set -a; . $WORKER_DIR/hub-worker.env; set +a; python3 $WORKER_DIR/arr_client.py --check" 2>&1)"
rc=$?
if echo "$m1" | jq -se 'length == 2' >/dev/null 2>&1; then
  val="$(echo "$m1" | jq -sc '[.[] | {service, transport, code, ms}]')"
  if [[ $rc == 0 ]]; then
    qc m1_arr_check pass "$val" "arr_client.py --check exit 0"
  else
    qc m1_arr_check fail "$val" "arr_client.py --check exit $rc"
  fi
else
  qc m1_arr_check fail null "arr_client.py --check did not print 2 JSON lines (deployed?): $(echo "$m1" | tail -1 | cut -c1-200)"
fi

finish
