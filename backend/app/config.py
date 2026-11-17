from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.paths import (
    AUTO_EDITOR_DIR,
    OPENSHORTS_DIR,
    ROOT,
    TWITCH_DOWNLOADER_CLI,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Cliperworld"
    data_dir: Path = ROOT / "data"
    # Prefer vendored TwitchDownloaderCLI release binary
    twitch_downloader_cli: str = str(TWITCH_DOWNLOADER_CLI)
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    # Prefer vendored auto-editor via python -m when installed editable
    auto_editor_bin: str = "auto-editor"
    whisperx_enabled: bool = True
    openshorts_dir: Path = OPENSHORTS_DIR
    auto_editor_dir: Path = AUTO_EDITOR_DIR
    chat_window_seconds: float = 8.0
    chat_spike_multiplier: float = 2.5
    chat_min_messages: int = 12
    clip_pre_seconds: float = 20.0
    clip_post_seconds: float = 25.0
    max_clips: int = 12
    # Prefer 720p for faster MVP downloads (1080p VODs can be multi-GB)
    twitch_download_quality: str = "720p60"
    # yt-dlp format string for YouTube
    youtube_format: str = "bv*[height<=720]+ba/b[height<=720]/b"
    youtube_retries: int = 12
    youtube_fragment_retries: int = 20
    youtube_socket_timeout: int = 30


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "jobs").mkdir(parents=True, exist_ok=True)
(settings.data_dir / "downloads").mkdir(parents=True, exist_ok=True)
(settings.data_dir / "clips").mkdir(parents=True, exist_ok=True)