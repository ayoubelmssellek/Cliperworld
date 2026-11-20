from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import settings

ProgressCb = Callable[[str, dict[str, Any]], None]


def yt_dlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401

        return True
    except ImportError:
        return shutil.which("yt-dlp") is not None


def fetch_youtube_info(url: str) -> dict[str, Any]:
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 30,
        "retries": 5,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    length = int(info.get("duration") or 0)
    thumbs = info.get("thumbnails") or []
    thumbnail = info.get("thumbnail")
    if not thumbnail and thumbs:
        thumbnail = thumbs[-1].get("url")

    return {
        "vod_id": str(info.get("id") or ""),
        "title": info.get("title") or "YouTube video",
        "streamer": info.get("uploader") or info.get("channel") or "YouTube",
        "streamer_login": info.get("uploader_id") or info.get("channel_id"),
        "category": (info.get("categories") or [None])[0],
        "views": info.get("view_count"),
        "length_seconds": length,
        "length_label": _fmt_seconds(length),
        "created_at": info.get("upload_date"),
        "thumbnail": thumbnail,
        "thumbnails": [t.get("url") for t in thumbs if t.get("url")][-4:],
        "platform": "youtube",
        "was_live": bool(info.get("was_live") or info.get("live_status") in {"was_live", "post_live"}),
    }


def download_youtube_video_and_chat(
    url: str,
    out_dir: Path,
    *,
    format_selector: str | None = None,
    fallback_format: str | None = None,
    on_progress: ProgressCb | None = None,
) -> tuple[Path, Path | None]:
    """
    Download YouTube video (+ live chat replay when available) via yt-dlp.
    Retries on flaky ConnectionReset / fragment errors.
    https://github.com/yt-dlp/yt-dlp
    """
    import yt_dlp
    from yt_dlp.utils import DownloadError

    out_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(out_dir / "%(id)s.%(ext)s")
    primary = format_selector or settings.youtube_format
    fallback = fallback_format or "b[height<=720]/b[height<=480]/b"

    def hook(d: dict[str, Any]) -> None:
        if not on_progress:
            return
        status = d.get("status")
        if status == "downloading":
            downloaded = int(d.get("downloaded_bytes") or 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            on_progress(
                "video_download_progress",
                {
                    "bytes": downloaded,
                    "bytes_label": _fmt_bytes(downloaded),
                    "total_bytes": int(total or 0),
                    "line": (d.get("_percent_str") or "").strip() or "downloading",
                },
            )
        elif status == "finished":
            on_progress("video_download_log", {"line": "Download finished, processing…"})

    if on_progress:
        on_progress("video_download_start", {"quality": primary, "output": str(out_dir)})

    # Try more stable clients / formats if YouTube resets the connection
    attempts: list[dict[str, Any]] = [
        {
            "format": primary,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        },
        {
            "format": primary,
            "extractor_args": {"youtube": {"player_client": ["ios", "web"]}},
        },
        {
            # Progressive single-file fallback (more reliable on bad networks)
            "format": fallback,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        },
    ]

    last_error: Exception | None = None
    info: dict[str, Any] | None = None

    for index, attempt in enumerate(attempts, start=1):
        opts: dict[str, Any] = {
            "outtmpl": outtmpl,
            "format": attempt["format"],
            "merge_output_format": "mp4",
            "writesubtitles": True,
            "writeautomaticsub": False,
            "subtitleslangs": ["live_chat"],
            "skip_download": False,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook],
            "overwrites": True,
            "continuedl": True,
            "retries": settings.youtube_retries,
            "fragment_retries": settings.youtube_fragment_retries,
            "file_access_retries": 5,
            "retry_sleep": {"http": 2, "fragment": 2, "file_access": 1},
            "socket_timeout": settings.youtube_socket_timeout,
            "concurrent_fragment_downloads": 1,  # more stable on reset-prone links
            "extractor_args": attempt.get("extractor_args"),
            "ignoreerrors": False,
        }
        if on_progress:
            on_progress(
                "video_download_log",
                {"line": f"Download attempt {index}/{len(attempts)}…"},
            )
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            break
        except DownloadError as exc:
            last_error = exc
            msg = str(exc)
            if on_progress:
                on_progress("video_download_log", {"line": f"Attempt {index} failed, retrying…"})
            # Brief pause before next client/format
            time.sleep(min(2 * index, 6))
            if not _is_retryable_download_error(msg) and index == 1:
                # Still try alternate clients once even for odd errors
                continue
            continue
        except Exception as exc:  # network stack weirdness
            last_error = exc
            time.sleep(min(2 * index, 6))
            continue

    if info is None:
        raise RuntimeError(_friendly_download_error(last_error)) from last_error

    video_id = str(info.get("id") or "video")
    video_path = _find_video(out_dir, video_id)
    if not video_path:
        raise RuntimeError(f"yt-dlp finished but no video found in {out_dir}")

    if on_progress:
        on_progress("chat_download_start", {"output": str(out_dir)})

    chat_path = _find_live_chat(out_dir, video_id)
    if chat_path and chat_path.suffix == ".json":
        normalized = out_dir / f"{video_id}.chat.json"
        if chat_path.resolve() != normalized.resolve():
            normalized.write_text(chat_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
            chat_path = normalized

    if on_progress:
        on_progress(
            "chat_download_done",
            {"output": str(chat_path) if chat_path else "", "has_chat": bool(chat_path)},
        )

    return video_path, chat_path


def _is_retryable_download_error(message: str) -> bool:
    text = message.lower()
    needles = [
        "connection reset",
        "connection broken",
        "forcibly closed",
        "timed out",
        "timeout",
        "10054",
        "eof occurred",
        "ssl",
        "http error 5",
        "fragment not found",
        "server returned 403",
        "server returned 429",
    ]
    return any(n in text for n in needles)


def _friendly_download_error(exc: Exception | None) -> str:
    raw = str(exc or "unknown download error")
    if _is_retryable_download_error(raw):
        return (
            "YouTube closed the download connection (network reset). "
            "This is usually temporary — click Find clips again. "
            f"Details: {raw[:300]}"
        )
    return f"YouTube download failed: {raw[:500]}"


def _find_video(out_dir: Path, video_id: str) -> Path | None:
    for ext in (".mp4", ".mkv", ".webm", ".mov"):
        candidate = out_dir / f"{video_id}{ext}"
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    matches = [
        p
        for p in out_dir.glob(f"{video_id}.*")
        if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"} and p.stat().st_size > 0
    ]
    return matches[0] if matches else None


def _find_live_chat(out_dir: Path, video_id: str) -> Path | None:
    patterns = [
        f"{video_id}.live_chat.json",
        f"{video_id}.en.live_chat.json",
        f"{video_id}.chat.json",
    ]
    for name in patterns:
        path = out_dir / name
        if path.exists() and path.stat().st_size > 0:
            return path
    matches = list(out_dir.glob(f"{video_id}*live_chat*.json"))
    return matches[0] if matches else None


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