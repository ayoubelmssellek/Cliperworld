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


def vendor_status() -> dict[str, bool]:
    return {
        "twitch_downloader_src": TWITCH_DOWNLOADER_SRC.exists(),
        "twitch_downloader_cli": TWITCH_DOWNLOADER_CLI.exists(),
        "openshorts": OPENSHORTS_DIR.exists(),
        "whisperX": WHISPERX_DIR.exists(),
        "PySceneDetect": PYSCENEDETECT_DIR.exists(),
        "auto_editor": AUTO_EDITOR_DIR.exists(),
        "remotion": REMOTION_DIR.exists(),
    }