# AP-9.0 social video probe (Cursor prompt)

Paste everything below the line into Cursor. It is read-only (metadata, no downloads), so it can run alongside AP-5a.1 r3 or OPS-ARR2. It does not restart anything.

---

ROLE: integrator / QC for Bucket-HUB (`llm-swarm-router`, app root `homelab/bucket-hub/`). This round is **probe and docs only**:
- no edits to application code, tests or smoke scripts;
- no deploys or restarts;
- no media downloads.

Never print cookies, tokens or keys, and never `cat` a cookies file.

PM CONTEXT: Finn wants the Hub to download from YouTube, X, Instagram, Threads, TikTok and similar sites, and pointed at <https://github.com/pablostanley/yoinks>. yoinks is a terminal UI around **yt-dlp**, which the Hub worker already runs. PM decision: bring yoinks' ideas into the Hub's video lane (social links detected, a format picker, per-site cookies, a Social segment) rather than run the yoinks TUI on the server. Spec: `homelab/bucket-hub/docs/pm/2026-10/AP-9-social-video.md`. This probe tells the PM which platforms work through Gluetun as the worker runs yt-dlp, and which need cookies.

PROTOCOL: `homelab/bucket-hub/docs/pm/PM-CURSOR-PROTOCOL.md` (`bucket-hub-qc/v1`).

OUTPUT: `homelab/bucket-hub/docs/pm/2026-10/qc/AP-9.0-r1.json`, committed on the local branch `pm/ap9-spec` and pushed (no PR). Reply = that JSON in one ```json block, then at most 5 lines.

## READ FIRST

1. `homelab/bucket-hub/docs/pm/2026-10/AP-9-social-video.md` § AP-9.0
2. `homelab/bucket-hub/hub-worker.py` `run_video_job` (read only: how the worker calls yt-dlp)
3. `homelab/bucket-hub/ytdlp-cookies-README.md`

## S0 URLs from Finn

Ask Finn in chat for **one public post per platform** that he is happy to test with. Prefer a short clip. Platforms: `youtube`, `x`, `instagram`, `threads`, `tiktok`, `facebook`, `reddit`. He may skip any; record skipped ones as `skip`. Do not choose URLs yourself.

## S1 probe (ai-server, through Gluetun, metadata only)

Run once per URL. `PLAT` is the platform id. `COOK` is `none`, or the cookies file for that platform if one exists (today only `~/homelab/data/ytdlp/cookies.txt`, the YouTube one):

```bash
ssh ai-server-ts 'PLAT=x URL="<url>" COOK=none; \
  C=""; [ "$COOK" != none ] && [ -s "$COOK" ] && C="-v $COOK:/c/cookies.txt:ro"; \
  start=$(date +%s); \
  docker run --rm --network container:gluetun $C python:3.11-slim bash -c \
    "pip install -q -U yt-dlp >/dev/null 2>&1; yt-dlp --version; \
     ${C:+cp /c/cookies.txt /tmp/c.txt &&} yt-dlp -J --skip-download --no-playlist ${C:+--cookies /tmp/c.txt} \"$URL\"" \
    > /tmp/ap9-$PLAT.json 2> /tmp/ap9-$PLAT.err; rc=$?; \
  echo "{\"platform\":\"$PLAT\",\"cookies\":\"$( [ -n "$C" ] && echo yes || echo no )\",\"rc\":$rc,\"secs\":$(( $(date +%s) - start ))}"; \
  sed -n 1p /tmp/ap9-$PLAT.json; \
  tail -n +2 /tmp/ap9-$PLAT.json | jq -c "{extractor: .extractor_key, title: (.title|.[0:60]), uploader, duration, max_height: ([.formats[]?.height // 0] | max), split_av: any(.formats[]?; .vcodec != \"none\" and .acodec == \"none\"), filesize_best: (.filesize // .filesize_approx), formats: (.formats | length)}" 2>/dev/null; \
  grep -m1 -E "ERROR|WARNING" /tmp/ap9-$PLAT.err | cut -c1-200'
```

If `jq` is missing on ai-server, drop the `jq` line, `scp ai-server-ts:/tmp/ap9-$PLAT.json /tmp/` and run the same filter on the Mac.

If a platform fails without cookies with a login or "rate-limit" error, record it. Do not add or export cookies this round; the PM sets that up in AP-9.1.

| id | expected |
|----|----------|
| `probe.<platform>` | `pass` if metadata came back. Value: `{rc, secs, ytdlp_version, extractor, max_height, split_av, formats, duration, cookies}`. `fail` with the first ERROR line (class: `login_required`, `rate_limited`, `geo`, `unsupported`, `other`). `skip` if Finn gave no URL |
| `info.ffmpeg_needed` | true if any `split_av` = true (merging needs ffmpeg in the image) |
| `info.ffmpeg_in_image` | `ssh ai-server-ts 'docker run --rm python:3.11-slim sh -c "command -v ffmpeg || echo missing"'` |
| `info.format_list_secs` | median `secs` (decides whether the Hub can show a live format picker) |
| `info.yoinks_note` | optional: if Finn runs `npx yoinks <url>` on his Mac for one platform, his one-line verdict; else `skip` |

## overall

This is a probe, so a `fail` on one platform is a finding, not a blocker. `overall` = `pass` if every non-skipped platform has been recorded (pass or fail with a class), else `blocked`.

## DOCUMENTS TO UPDATE (only these)

- `qc/AP-9.0-r1.json` (new).
- `docs/pm/2026-10/AP-9-social-video.md`: add a "Probe results (r1)" table under § AP-9.0, one row per platform.
- `docs/agent-context/PROJECT-STATE.md`: one session-log row citing the QC file.

Clean up `/tmp/ap9-*` on ai-server when done.
