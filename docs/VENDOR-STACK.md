# Vendor stack — best of each repo

Cliperworld does **not** rewrite clip engines. We clone real tools into `vendor/`
and call what each one does best.

## Capability map

| Repo | License | Best at | Wired into Cliperworld |
|---|---|---|---|
| [TwitchDownloader](https://github.com/lay295/TwitchDownloader) | MIT | Twitch VOD + chat download | Download stage |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense | YouTube + live chat | Download stage |
| [**Clips Kitty / clips-studio**](https://github.com/ColinGPT9/clips-studio) | **AGPL-3.0** | Full Opus-Clip-class brain | See below |
| [Vertify](https://github.com/daylennguyen/vertify) | MIT | Simple 16:9→9:16 blur | Shorts fallback |
| [OpenShorts](https://github.com/mutonby/openshorts) | MIT | Face-tracked reframe + captions | Shorts / burn fallback |
| [WhisperX](https://github.com/m-bain/whisperX) / faster-whisper | BSD | Word-level transcription | Captions + Gemma transcript |
| [Auto-Editor](https://github.com/WyattBlue/auto-editor) | Unlicense | Silence trim | Optional tighten |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | BSD | Scene boundaries | Snap cut points |
| FFmpeg | LGPL/GPL | Cut / encode | Everywhere |
| [StreamCut](https://github.com/xAmirHamza77/StreamCut) | MIT | YuNet facecam inset (filters in-game faces) | ✅ `streamcut_facecam.py` → cam layouts |
| [Auto-Clipper](https://github.com/gummybearansh/Auto-Clipper) | (see repo) | YuNet + sticky overlay borders | vendored reference / fallback model |
| [Gaming-Clipper](https://github.com/HmdNvd/Gaming-Clipper) | (see repo) | Full 16:9 gameplay keep + corner cam | vendored reference for HUD-safe crop |

---

## What Clips Kitty’s README actually gives us

From their pipeline (Gemma is the local brain via **Ollama**):

| Clips Kitty piece | What it does | Cliperworld status |
|---|---|---|
| **Gemma + Ollama** (`llm/`, `score_clips.txt`) | LLM picks viral moments 0–100 | ✅ `kitty_brain.py` when Ollama + Gemma installed |
| **Multimodal fusion** (`analysis/fusion.py`) | Audio + visual + reaction + text | ⏳ next (needs their feature extractors) |
| **chat_moments** | POG / KEKW / CLIP IT classes | ✅ boosts chat spikes + feeds Gemma events |
| **fit_blur cropper** | 9:16 letterbox Shorts | ✅ primary Shorts packager |
| **Gaming / Reaction layouts** | Webcam + game split for streams | ✅ `cam_hook_game` / `game_hook_cam` layout picker |
| **TalkNet + YOLOv8 tracking** | Follow who is speaking | ⏳ next |
| **AI titles / hashtags** (`metadata.txt`) | Shorts packaging copy | ✅ with Gemma scoring |
| **Sports (soccer / basketball)** | Ball / scorebug moments | later |
| **Publish / multilingual / dubbing** | Distribution | later |

### Enable Gemma (required for the AI brain)

1. Install [Ollama](https://ollama.com) for Windows  
2. Pull a model Clips Kitty recommends, e.g.:

```powershell
ollama pull gemma:7b
# lighter CPU: ollama pull gemma3:4b
# stronger GPU: ollama pull gemma3:12b
```

3. Restart the Cliperworld API — `/api/health` should show `ollama: true`, `gemma: true`

Without Ollama, Cliperworld still works (chat spikes + Vertify/OpenShorts Shorts).

---

## Pipeline roles

```text
URL → TwitchDownloader / yt-dlp
    → chat spikes + Clips Kitty chat_moments
    → [if Gemma] faster-whisper transcript → Clips Kitty score_clips + metadata
    → FFmpeg cut (+ PySceneDetect / Auto-Editor)
    → 9:16 layout picker: blur | cam_hook_game | game_hook_cam | face
         (Kitty split + hook banner, or fit_blur / Vertify / OpenShorts)
    → captions: OpenShorts karaoke ASS (word highlight)
```

## Rule for new repos

1. Clone into `vendor/` via `scripts/fetch-vendor.ps1`
2. **Read their README** — list every powerful subsystem
3. Wire a thin glue module under `backend/app/pipeline/`
4. Prefer calling their code/CLI over rewriting
5. Note license (AGPL tools stay isolated under `vendor/`)

## Fetch

```powershell
.\scripts\fetch-vendor.ps1
```
