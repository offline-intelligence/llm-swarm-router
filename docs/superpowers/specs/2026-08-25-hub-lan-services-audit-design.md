# Hub LAN services audit (home network only)

Date: 2026-08-25  
Status: done (2026-08-25) — see results doc  

## Goal

Confirm AriaNg, MeTube, Jellyfin, Uptime Kuma, TNAS, and netllm (Mac/Ubuntu) are reachable on LAN, correctly linked from Glance Hub, and not accidentally public.

## In / Out

| In | Out |
|----|-----|
| Reachability smoke from Pi + notes | Redesigning each app’s UI |
| Glance widget URL / same-origin fixes | Cloudflare publishing of LAN tools |
| Basic bind/auth hygiene notes | Full Jellyfin library curation |

## Services

| Service | Expected LAN URL | Host |
|---------|------------------|------|
| AriaNg | `:8088` | Ubuntu |
| MeTube | `:8089` | Ubuntu (via Gluetun publish) |
| Jellyfin | `:8096` | Ubuntu |
| Uptime Kuma | `:3001` | Pi |
| TNAS | `:80` / NAS UI | `192.168.50.187` |
| netllm Mac | `:11400/ui/` | Mac |
| netllm Ubuntu | `:11400/ui/` | Ubuntu |

## Acceptance

1. Written audit table: up / down / notes per service.  
2. Glance Hub LAN links match working URLs.  
3. No LAN admin UIs exposed via public tunnel paths (spot-check).  
4. TODO updated.
