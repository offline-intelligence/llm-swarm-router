# AP-9: social video downloads (YouTube, X, Instagram, Threads, TikTok), yoinks approach

**Asked by:** Finn, 2026-10-12: "integrate this repo as a way to download youtube, X, instagram, etc." Repo: <https://github.com/pablostanley/yoinks> (MIT).  
**Status:** backlog. The probe (AP-9.0) can run now; PM builds AP-9.1 after OPS-ARR2 and AP-5a.2.

## What yoinks is (read 2026-10-12)

- A TypeScript, Node 18+ CLI with a full-screen terminal UI (Ink). Install with `npm i -g yoinks`; run with `yoinks <url>`.
- It wraps **yt-dlp**: it downloads the standalone binary to `~/.yoinks/bin` on first run. It uses **ffmpeg** to merge streams and to make mp3.
- Its README names YouTube, X/Twitter, Instagram, Threads and TikTok, plus the "1,800+" sites yt-dlp supports.
- It always saves to `~/Downloads`. Its roadmap still lists, unchecked: `--best` / `--mp3` flags, `-o <dir>`, playlists and multi-video threads, and self-update.

## PM recommendation: take the approach, not the binary

The Hub already runs yt-dlp. The worker's `run_video_job` runs it in a container on Gluetun, with YouTube cookies. yoinks adds a format picker and a list of social sites on top of the same yt-dlp. As a server component it has three gaps today:
- It is interactive.
- It cannot choose an output folder.
- It cannot run unattended.

Running it on ai-server would mean screen-scraping a TUI to reach the yt-dlp we already call. So AP-9 brings what yoinks does well into the Hub's own video lane:

| yoinks idea | Hub change (AP-9.1) |
|-------------|---------------------|
| Paste any social link | `detect_kind` maps `x.com`, `twitter.com`, `instagram.com`, `threads.net`, `tiktok.com`, `facebook.com/…/videos`, `reddit.com`, `vimeo.com` and YouTube to `video` (today only YouTube, Vimeo and TikTok). The worker records `platform`. |
| Format picker | **Best**, **1080p**, **720p** and **Audio (mp3)** chips on the Video preset. Each maps to a yt-dlp `-f` / `-S` / `-x` option. A server-side `GET /api/video/formats?url=` (yt-dlp `-J`) is optional, only if the probe shows it is fast enough. |
| Works without ads, no account | Per-site cookies where a site needs login: `~/homelab/data/ytdlp/cookies-<platform>.txt` (mode 600, never in git), falling back to today's `cookies.txt`. A clear "needs cookies" job error per platform. |
| Saves to Downloads | A **Social** segment with presets that save to `videos/social/<platform>/<uploader>/`, plus the existing "Manually set path". |
| Personal archiving | An index entry (AP-5c video builder) with the platform, uploader, post URL, caption excerpt and upload date, and an `ABOUT-THIS-DOWNLOAD.md` beside multi-file posts. |

**Out of scope for AP-9.1:**
- Image-only posts and carousels. yt-dlp fetches only videos from these; a `gallery-dl` lane would be AP-9.2 if Finn wants it.
- Private accounts.
- Bulk profile scraping.

yoinks stays available as a personal tool on Finn's Mac (`npx yoinks`). That needs no Hub change.

**Use:** personal archiving only. Respect each platform's terms and only keep what you have the right to keep, as yoinks' own README says.

## AP-9.0 probe (Cursor, metadata only, no downloads)

Run `yt-dlp -J --skip-download` from ai-server through Gluetun, the same way the worker does (`docker run --rm --network container:gluetun python:3.11-slim`, then `pip install -U yt-dlp`). Use one public URL per platform, which Finn supplies, first without cookies and then with them where a cookies file exists. Record per platform:
- whether metadata comes back, and the error class if not (login required, rate-limited, geo, extractor error);
- the best format height, whether audio and video are separate (needs ffmpeg), and filesize or duration;
- the time taken, and the yt-dlp version.

The QC JSON (`qc/AP-9.0-r1.json`) decides which platforms need cookies, and whether a live format list is fast enough for the picker.

### Probe results (r1)

| Platform | URL (Finn) | Cookies | Result | Class | max_height | split_av | secs | Notes |
|----------|------------|---------|--------|-------|------------|----------|------|-------|
| youtube | — | — | **blocked** | — | — | — | — | awaiting S0 URLs |
| x | — | — | **blocked** | — | — | — | — | awaiting S0 URLs |
| instagram | — | — | **blocked** | — | — | — | — | awaiting S0 URLs |
| threads | — | — | **blocked** | — | — | — | — | awaiting S0 URLs |
| tiktok | — | — | **blocked** | — | — | — | — | awaiting S0 URLs |
| facebook | — | — | **blocked** | — | — | — | — | awaiting S0 URLs |
| reddit | — | — | **blocked** | — | — | — | — | awaiting S0 URLs |

QC: `docs/pm/2026-10/qc/AP-9.0-r1.json` (**overall blocked**, 2026-10-12).

### Probe results (r2)

Finn cut scope: **Threads** and **TikTok** not probed (Hub social lane does not need them). Five platforms through Gluetun (`yt-dlp` 2026.08.19 in `python:3.11-slim`).

| platform | url | result | error class | max height | split A/V | secs |
|----------|-----|--------|-------------|------------|-----------|------|
| youtube | https://www.youtube.com/watch?v=usSfgHGEGxQ | pass | — | 1080 | yes | 16 |
| x | https://x.com/damkina7/status/2109275362660130919 | pass | — | 1440 | yes | 16 |
| instagram | https://www.instagram.com/reel/C6xRGVRO20f/ | fail | login_required | — | — | 16 |
| threads | — | skip | — | — | — | — |
| tiktok | — | skip | — | — | — | — |
| facebook | https://www.facebook.com/NASA/videos/313731330445028/ | fail | other | — | — | 13 |
| reddit | https://www.reddit.com/r/videos/comments/1c9xj0o/worlds_largest_drum/ | fail | other | — | — | 16 |

QC: `docs/pm/2026-10/qc/AP-9.0-r2.json` (**overall pass**, 2026-10-12). `info.ffmpeg_needed` true; ffmpeg **missing** in `python:3.11-slim`; median format-list time **16 s**.

## AP-9.1 build (PM): slimmed to YouTube polish (Finn, 2026-10-12)

Finn mainly wanted YouTube, which the Hub already downloads (same yt-dlp, same cookies the probe used). The broad social lane (per-site cookies, platform registry, Social segment, Instagram/Facebook/Reddit) is **dropped**. AP-9.1 is now a small slice:

| Item | What |
|------|------|
| Resolution chips | **Best** / **1080p** / **720p** on the Video preset (`options.format`, mapped to `-S res:<h>`). mp3 stays the existing `extract_audio` option. Fixed chips, because a metadata call takes about 16 s. |
| X links | `detect_kind`: `x.com` / `twitter.com` → `video` (probe r2: works without cookies, up to 1440p). |
| One image, with ffmpeg | Every video job runs in `METUBE_IMAGE` (yt-dlp, Deno, ffmpeg; YouTube already used it). `python:3.11-slim` has no ffmpeg, so split audio/video (YouTube, X) could not merge outside the YouTube path. This also drops the per-job `pip install -U yt-dlp`. Cursor confirms `ffmpeg -version` in that image. |
| Tests + smoke | chip → args; X detection; image choice. Smoke: download the probe r2 YouTube and X clips (size cap 200 MB) and confirm the merged file has audio and video (`ffprobe`). |

Probe r2 findings kept for reference: Instagram needs login cookies, Facebook's extractor was broken, Reddit blocks VPN exits. Revisit only if Finn asks.

Order: a small slice after AP-5a.2.
