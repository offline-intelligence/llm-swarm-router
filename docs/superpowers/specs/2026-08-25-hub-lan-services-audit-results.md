# Hub LAN services audit — results

Date: 2026-08-25  
Probed from Pi `192.168.50.138` and Ubuntu `ai-server` (`192.168.50.65`).

## Summary

| Service | LAN URL | From Pi | Notes |
|---------|---------|---------|--------|
| AriaNg | `http://192.168.50.65:8088/` | **OK** 200 | UI up; RPC is aria2 on `:6800` (Gluetun publish). Set AriaNg RPC to `http://192.168.50.65:6800/jsonrpc` + secret from Ubuntu `.env` `ARIA2_RPC_SECRET`. |
| MeTube | `http://192.168.50.65:8089/` | **OK** 200 | Via Gluetun; YouTube cookies mounted. |
| Jellyfin | `http://192.168.50.65:8096/` | **OK** 200 | `JELLYFIN_PublishedServerUrl` already LAN IP. Media bind `/mnt/media:ro`. |
| Uptime Kuma | `http://192.168.50.138:3001/` | **OK** 200 | Pi-local. Off-LAN browsers need Tailscale to open this link. |
| TNAS | `http://192.168.50.187/` | **OK** 200 | TOS UI loads. |
| netllm Ubuntu | `http://192.168.50.65:11400/ui/` | **OK** 200 | Peer role; listen `192.168.50.65:11400`. |
| netllm Mac | `http://192.168.50.19:11400/ui/` | **DOWN** | Host unreachable (ping loss). Start Mac / netllm when needed. |
| Bucket-HUB | `:3000` / Access hostname | **OK** | Caddy only proxies Glance + `/hub-form` + `/status` — not AriaNg/MeTube/Jellyfin. |
| Public tunnel | `https://bucket-hub.stackrise.com.au` | **Access-gated** | Paths return **302** (Access); no LAN app HTML leaked in spot-check. |

### Also on Ubuntu (Hub-related, not previously on Glance LAN list)

| Service | Port | Notes |
|---------|------|--------|
| SearXNG | `:8888` | Proton search; LAN UI optional. |
| Jackett | `:9117` | Indexer config UI; keep LAN-only. |
| aria2 RPC | `:6800` | Used by AriaNg / Hub worker; published on Gluetun. |

## Public exposure

- **Good:** `hub-gateway` Caddyfile has no reverse_proxy to `:8088` / `:8089` / `:8096` / `:9117`.
- **Note:** Several services bind `0.0.0.0` on Ubuntu (LAN + Tailscale). That is intentional for phone-via-Tailscale; they are **not** on the Cloudflare tunnel. Guest Wi‑Fi users on the home LAN can still reach them unless isolated by AP/VLAN.

## Actions taken

1. Documented this audit (spec + results).  
2. Glance **LAN** monitor: clarify title; add SearXNG + Jackett; leave netllm Mac URL (shows down until Mac is up).  
3. TODO marked complete for this audit item.

## Maintainer follow-ups (optional)

- [x] **AriaNg RPC** (2026-08-26): aria2 RPC OK on Ubuntu; `scripts/ariang-wire-rpc.sh` one-shot AriaNg setup URL (base64url secret). Re-open URL if browser localStorage cleared.
- [ ] **MeTube cookies**: refresh Netscape cookies after 429 on Proton exit.
- [ ] **Jackett**: set admin password; rotate API key if leaked in screenshots.
- [ ] **Uptime Kuma**: complete `/setup` on Pi `:3001` + monitors.
- [ ] When Mac is on: confirm netllm LAN listen + Hub monitor green.
- [ ] Longer term: guest Wi‑Fi VLAN so media UIs aren’t on the IoT SSID.
- [ ] Optional: Tailscale MagicDNS names in a Hub “away” doc (not Glance, which is LAN-first).
