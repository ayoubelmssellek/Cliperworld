from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import settings
from app.paths import TWITCH_DOWNLOADER_CLI

VOD_PATTERNS = [
    re.compile(r"twitch\.tv/videos/(\d+)", re.I),
    re.compile(r"twitch\.tv/\w+/v/(\d+)", re.I),
]

ProgressCb = Callable[[str, dict[str, Any]], None]


def parse_twitch_vod_id(url: str) -> str | None:
    for pattern in VOD_PATTERNS:
        match = pattern.search(url.strip())
        if match:
            return match.group(1)
    if url.strip().isdigit():
        return url.strip()
    return None


def resolve_twitch_cli() -> Path:
    configured = Path(settings.twitch_downloader_cli)
    if configured.exists():
        return configured
    if TWITCH_DOWNLOADER_CLI.exists():
        return TWITCH_DOWNLOADER_CLI
    raise RuntimeError(
        "Vendored TwitchDownloaderCLI missing. Expected at "
        f"{TWITCH_DOWNLOADER_CLI}. Run scripts/fetch-vendor.ps1"
    )


def twitch_downloader_available() -> bool:
    try:
        return resolve_twitch_cli().exists()
    except RuntimeError:
        return False


def resolve_latest_vod_from_channel(channel: str) -> tuple[str, str]:
    """
    Resolve https://www.twitch.tv/{channel} → latest VOD URL + id.
    Uses yt-dlp flat playlist of the channel videos page.
    """
    import yt_dlp

    login = channel.strip().lstrip("@")
    playlist = f"https://www.twitch.tv/{login}/videos?filter=archives&sort=time"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": 5,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(playlist, download=False)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load VODs for Twitch channel '{login}'. "
            f"Paste a VOD link like https://www.twitch.tv/videos/123456789 instead. ({exc})"
        ) from exc

    entries = info.get("entries") if isinstance(info, dict) else None
    if not entries:
        raise RuntimeError(
            f"No VODs found for Twitch channel '{login}'. "
            "They may have VODs disabled, or nothing archived yet."
        )

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        vod_id = str(entry.get("id") or "").strip()
        # Twitch VOD ids are numeric; skip clips/highlights if mixed in
        if not vod_id.isdigit():
            url = str(entry.get("url") or entry.get("webpage_url") or "")
            parsed = parse_twitch_vod_id(url)
            if parsed:
                vod_id = parsed
        if vod_id.isdigit():
            return f"https://www.twitch.tv/videos/{vod_id}", vod_id

    raise RuntimeError(
        f"No archive VODs found for '{login}'. Paste a direct VOD URL instead."
    )


def fetch_vod_info(vod_id: str) -> dict[str, Any]:
    """
    TwitchDownloaderCLI info --format Raw
    Returns streamer, title, thumbnails, length, etc.
    """
    cli = str(resolve_twitch_cli())
    cmd = [
        cli,
        "info",
        "--id",
        vod_id,
        "--format",
        "Raw",
        "--banner",
        "false",
        "--log-level",
        "None",
    ]
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"TwitchDownloader info failed: {detail or exc}") from exc

    # Raw mode prints multiple JSON blobs + m3u; first object is video info
    video: dict[str, Any] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        candidate = (payload.get("data") or {}).get("video") or {}
        if candidate.get("title") or candidate.get("thumbnailURLs"):
            video = candidate
            break

    thumbs = video.get("thumbnailURLs") or []
    # Prefer a larger thumb if Twitch only gave 320x180 — swap size in URL
    cover = thumbs[0] if thumbs else None
    if cover and "320x180" in cover:
        cover_large = cover.replace("320x180", "1280x720")
    else:
        cover_large = cover

    length_seconds = int(video.get("lengthSeconds") or 0)
    owner = video.get("owner") or {}
    game = video.get("game") or {}
    return {
        "vod_id": vod_id,
        "title": video.get("title") or f"VOD {vod_id}",
        "streamer": owner.get("displayName") or owner.get("login") or "Unknown",
        "streamer_login": owner.get("login"),
        "category": game.get("displayName"),
        "views": video.get("viewCount"),
        "length_seconds": length_seconds,
        "length_label": _fmt_seconds(length_seconds),
        "created_at": video.get("createdAt"),
        "thumbnail": cover_large or cover,
        "thumbnails": thumbs,
    }


def download_vod_and_chat(
    vod_id: str,
    out_dir: Path,
    *,
    quality: str | None = None,
    on_progress: ProgressCb | None = None,
) -> tuple[Path, Path]:
    """
    Calls the real TwitchDownloaderCLI from vendor/bin
    (source: vendor/TwitchDownloader → https://github.com/lay295/TwitchDownloader)
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cli = str(resolve_twitch_cli())
    video_out = out_dir / f"{vod_id}.mp4"
    chat_out = out_dir / f"{vod_id}.chat.json"
    q = quality or settings.twitch_download_quality

    def emit(phase: str, **extra: Any) -> None:
        if on_progress:
            on_progress(phase, extra)

    video_cmd = [
        cli,
        "videodownload",
        "--id",
        vod_id,
        "-o",
        str(video_out),
        "-q",
        q,
        "--collision",
        "Overwrite",
        "--banner",
        "false",
        "--log-level",
        "Status,Info,Warning,Error",
    ]
    emit("video_download_start", quality=q, output=str(video_out))
    _run_with_progress(video_cmd, "TwitchDownloader videodownload", out_dir, on_progress)

    chat_cmd = [
        cli,
        "chatdownload",
        "--id",
        vod_id,
        "-o",
        str(chat_out),
        "--embed-images",
        "False",
        "--collision",
        "Overwrite",
        "--banner",
        "false",
        "--log-level",
        "Status,Info,Warning,Error",
    ]
    emit("chat_download_start", output=str(chat_out))
    _run(chat_cmd, "TwitchDownloader chatdownload")
    emit("chat_download_done", output=str(chat_out))

    if not video_out.exists():
        candidates = [
            p
            for p in out_dir.glob(f"{vod_id}.*")
            if p.suffix.lower() in {".mp4", ".mkv", ".ts", ".m4a"}
        ]
        if not candidates:
            raise RuntimeError(f"TwitchDownloader finished but no media in {out_dir}")
        video_out = candidates[0]

    if not chat_out.exists():
        raise RuntimeError(f"TwitchDownloader chat file missing: {chat_out}")

    return video_out, chat_out


def _run(cmd: list[str], label: str) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label} failed: executable not found ({cmd[0]})") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"{label} failed: {detail or exc}") from exc


def _run_with_progress(
    cmd: list[str],
    label: str,
    watch_dir: Path,
    on_progress: ProgressCb | None,
) -> None:
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label} failed: executable not found ({cmd[0]})") from exc

    stop = threading.Event()

    def watch_files() -> None:
        while not stop.wait(1.5):
            total = 0
            newest = ""
            try:
                for path in watch_dir.rglob("*"):
                    if path.is_file():
                        total += path.stat().st_size
                        newest = path.name
            except OSError:
                continue
            if on_progress:
                on_progress(
                    "video_download_progress",
                    {
                        "bytes": total,
                        "bytes_label": _fmt_bytes(total),
                        "newest_file": newest,
                    },
                )

    watcher = threading.Thread(target=watch_files, daemon=True)
    watcher.start()

    lines: list[str] = []
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            text = line.strip()
            if not text:
                continue
            lines.append(text)
            if on_progress and ("%" in text or "Downloading" in text or "STATUS" in text):
                on_progress("video_download_log", {"line": text[-240:]})
        code = proc.wait()
    finally:
        stop.set()
        watcher.join(timeout=2)

    if code != 0:
        detail = "\n".join(lines[-20:])
        raise RuntimeError(f"{label} failed: {detail or code}")


def _fmt_seconds(total: int) -> str:
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{n} B"