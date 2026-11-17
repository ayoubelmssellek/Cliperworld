# Vendored stack (real repos)

These are the tools Cliperworld is built on — cloned / downloaded here, not rewritten.

| Path | Source | Used for |
|---|---|---|
| `TwitchDownloader/` | https://github.com/lay295/TwitchDownloader | Source tree |
| `bin/TwitchDownloaderCLI/` | Official release binary 1.56.5 | Download Twitch VOD + chat |
| `openshorts/` | https://github.com/mutonby/openshorts | Clip selection, captions, Shorts pipeline |
| `whisperX/` | https://github.com/m-bain/whisperX | Transcription |
| `PySceneDetect/` | https://github.com/Breakthrough/PySceneDetect | Scene cuts |
| `auto-editor/` | https://github.com/WyattBlue/auto-editor | Silence removal |
| `remotion/` | https://github.com/remotion-dev/remotion | Layout rendering (npm packages; full monorepo too large to vendor) |

FFmpeg stays a system binary (`ffmpeg` on PATH).

Re-fetch everything:

```powershell
.\scripts\fetch-vendor.ps1
```
