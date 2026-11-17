# Cliperworld

Web app that turns **Twitch VODs** and **YouTube** videos into Shorts-ready clips by detecting **chat blow-ups** (or audio spikes when chat is missing), cutting around those moments, then optionally adding captions.

Kick + live mode come next.

Only clip streamers who allow it.

---

## What your friend needs installed

| Requirement | Notes |
|---|---|
| **Git** | To clone this repo + vendor tools |
| **Python 3.11+** | Backend API |
| **Node.js 20+** | Frontend |
| **FFmpeg** | Must be on PATH (`ffmpeg -version`) |
| **yt-dlp** | Installed via `pip install -r requirements.txt` (YouTube) |
| **Windows** | TwitchDownloaderCLI `.exe` fetch script targets Windows |

---

## Quick start (after `git clone`)

### 1. Get the real tool repos (required)

The engines live in `vendor/` (not rewritten in this repo). Fetch them:

```powershell
cd cliperworld
.\scripts\fetch-vendor.ps1
```

This clones / downloads:

- [TwitchDownloader](https://github.com/lay295/TwitchDownloader) (+ Windows CLI binary)
- [OpenShorts](https://github.com/mutonby/openshorts)
- [WhisperX](https://github.com/m-bain/whisperX)
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect)
- [Auto-Editor](https://github.com/WyattBlue/auto-editor)

Check: `vendor\bin\TwitchDownloaderCLI\TwitchDownloaderCLI.exe` should exist.

### 2. Backend

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

### 3. Frontend (new terminal)

```powershell
cd frontend
npm install
npm run dev
```

Open **http://127.0.0.1:5173**

You should see tool pills like `ffmpeg: ready`, `twitch downloader: ready`, and `yt dlp: ready`.

### 4. Clip a video

1. Paste a **Twitch VOD** (`https://www.twitch.tv/videos/...`) or **YouTube** link
2. Click **Find clips**
3. Watch cover + progress (download → chat → spikes → cut → captions)
4. Download finished clips from the job panel

**Twitch:** downloads via TwitchDownloaderCLI at **720p60** by default.  
**YouTube:** downloads via **yt-dlp**; uses live chat when available, otherwise audio spikes.  
Long videos still take time.

Optional: copy `.env.example` → `.env` to change quality / paths.

---

## Project layout

```text
cliperworld/
  backend/     FastAPI job API + pipeline glue
  frontend/    Vite + React UI
  vendor/      Real open-source tools (fetched locally)
  scripts/     fetch-vendor.ps1
  data/        downloads / jobs / clips (created at runtime, not in git)
```

## Stack

| Tool | Role |
|---|---|
| TwitchDownloaderCLI | Download Twitch VOD + chat |
| yt-dlp | Download YouTube video + live chat |
| Chat / audio spike detector | Find hype moments (no AI required) |
| FFmpeg | Cut / encode |
| Auto-Editor | Optional silence trim |
| PySceneDetect | Optional snap to scene cuts |
| WhisperX + OpenShorts | Optional captions |

## API (optional)

- `GET /api/health` — tool readiness
- `POST /api/jobs` — `{ "url": "...", "with_captions": true }`
- `GET /api/jobs/{id}` — status + clips
- `GET /api/jobs/{id}/clips/{clip_id}/download`

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `twitch downloader: missing` | Run `.\scripts\fetch-vendor.ps1` |
| `ffmpeg: missing` | Install FFmpeg and restart the terminal |
| Job stuck on download | Long VOD — watch progress % / bytes; try a shorter VOD |
| Captions skipped | WhisperX/OpenShorts deps may be incomplete; clips still download without captions |
| Port in use | Change `--port 8000` or Vite port |

## Notes for contributors

- Do **not** commit `vendor/` binaries/clones (too large). Friends always run `fetch-vendor.ps1`.
- Do **not** commit `data/` (downloaded VODs / clips).
