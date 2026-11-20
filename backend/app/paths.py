from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor"

TWITCH_DOWNLOADER_SRC = VENDOR / "TwitchDownloader"
TWITCH_DOWNLOADER_CLI = VENDOR / "bin" / "TwitchDownloaderCLI" / "TwitchDownloaderCLI.exe"
OPENSHORTS_DIR = VENDOR / "openshorts"
WHISPERX_DIR = VENDOR / "whisperX"
PYSCENEDETECT_DIR = VENDOR / "PySceneDetect"
AUTO_EDITOR_DIR = VENDOR / "auto-editor"
REMOTION_DIR = VENDOR / "remotion"
CLIPS_STUDIO_DIR = VENDOR / "clips-studio"
STREAMCUT_DIR = VENDOR / "StreamCut"
AUTO_CLIPPER_DIR = VENDOR / "Auto-Clipper"
GAMING_CLIPPER_DIR = VENDOR / "Gaming-Clipper"
VERTIFY_DIR = VENDOR / "bin" / "vertify"


def _find_vertify() -> Path:
    direct = VERTIFY_DIR / "vertify.exe"
    if direct.exists():
        return direct
    if VERTIFY_DIR.exists():
        for path in VERTIFY_DIR.rglob("vertify.exe"):
            return path
    return direct


VERTIFY_CLI = _find_vertify()


def vendor_status() -> dict[str, bool]:
    return {
        "twitch_downloader_src": TWITCH_DOWNLOADER_SRC.exists(),
        "twitch_downloader_cli": TWITCH_DOWNLOADER_CLI.exists(),
        "openshorts": OPENSHORTS_DIR.exists(),
        "whisperX": WHISPERX_DIR.exists(),
        "PySceneDetect": PYSCENEDETECT_DIR.exists(),
        "auto_editor": AUTO_EDITOR_DIR.exists(),
        "remotion": REMOTION_DIR.exists(),
        "clips_studio": CLIPS_STUDIO_DIR.exists(),
        "streamcut": STREAMCUT_DIR.exists(),
        "auto_clipper": AUTO_CLIPPER_DIR.exists(),
        "gaming_clipper": GAMING_CLIPPER_DIR.exists(),
        "vertify": VERTIFY_CLI.exists(),
    }