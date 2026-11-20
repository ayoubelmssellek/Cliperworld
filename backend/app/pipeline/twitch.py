from __future__ import annotations

import json
import re
import shutil
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
# Event (not Lock) so Stop / cancel can clear a stuck download from any thread
_download_busy = threading.Event()
_active_proc_lock = threading.Lock()
_active_proc: subprocess.Popen[str] | None = None
_force_stopped = False
_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")


def download_busy() -> bool:
    return _download_busy.is_set()


def force_stop_download() -> None:
    """Kill the active TwitchDownloader process and free the download gate."""
    global _active_proc, _force_stopped
    _force_stopped = True
    with _active_proc_lock:
        proc = _active_proc
        _active_proc = None
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=4)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    _download_busy.clear()


def _consume_force_stopped() -> bool:
    global _force_stopped
    was = _force_stopped
    _force_stopped = False
    return was


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
    Fast metadata via yt-dlp first; fall back to TwitchDownloaderCLI info.
    """
    try:
        return _fetch_vod_info_ytdlp(vod_id)
    except Exception:
        return _fetch_vod_info_twitchdownloader(vod_id)


def _fetch_vod_info_ytdlp(vod_id: str) -> dict[str, Any]:
    import yt_dlp

    url = f"https://www.twitch.tv/videos/{vod_id}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 20,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    length = int(info.get("duration") or 0)
    thumbs = [t.get("url") for t in (info.get("thumbnails") or []) if t.get("url")]
    thumbnail = info.get("thumbnail") or (thumbs[-1] if thumbs else None)
    return {
        "vod_id": vod_id,
        "title": info.get("title") or f"VOD {vod_id}",
        "streamer": info.get("uploader") or info.get("channel") or "Unknown",
        "streamer_login": info.get("uploader_id") or info.get("channel_id"),
        "category": None,
        "views": info.get("view_count"),
        "length_seconds": length,
        "length_label": _fmt_seconds(length),
        "created_at": info.get("timestamp") or info.get("upload_date"),
        "thumbnail": thumbnail,
        "thumbnails": thumbs[-4:],
    }


def _fetch_vod_info_twitchdownloader(vod_id: str) -> dict[str, Any]:
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
    cover = thumbs[0] if thumbs else None
    cover_large = cover.replace("320x180", "1280x720") if cover and "320x180" in cover else cover
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
) -> tuple[Path, Path | None]:
    """
    Calls the real TwitchDownloaderCLI from vendor/bin
    (source: vendor/TwitchDownloader → https://github.com/lay295/TwitchDownloader)

    Chat is best-effort: if chatdownload hangs/fails, returns (video, None)
    so the pipeline can fall back to audio spikes.
    """
    # One Twitch download at a time — parallel CLI processes starve each other
    if _download_busy.is_set():
        raise RuntimeError(
            "Another Twitch download is already running. Press Stop on that job "
            "(or wait for it to finish), then try again."
        )
    global _force_stopped
    _force_stopped = False
    _download_busy.set()

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = out_dir / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        cli = str(resolve_twitch_cli())
        video_out = out_dir / f"{vod_id}.mp4"
        chat_out = out_dir / f"{vod_id}.chat.json"
        q = quality or settings.twitch_download_quality
        threads = str(max(4, min(settings.twitch_download_threads, 12)))

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
            "-t",
            threads,
            "--temp-path",
            str(temp_dir),
            "--collision",
            "Overwrite",
            "--banner",
            "false",
            "--log-level",
            "Status,Info,Warning,Error",
        ]
        reused = _reuse_existing_vod(vod_id, video_out)
        if reused is not None:
            emit(
                "video_download_skip",
                quality=q,
                output=str(video_out),
                bytes=reused,
                bytes_label=_fmt_bytes(reused),
            )
        else:
            emit("video_download_start", quality=q, output=str(video_out), threads=threads)
            _run_with_progress(video_cmd, "TwitchDownloader videodownload", out_dir, on_progress)

        if not video_out.exists():
            candidates = [
                p
                for p in out_dir.glob(f"{vod_id}.*")
                if p.suffix.lower() in {".mp4", ".mkv", ".ts", ".m4a"}
            ]
            if not candidates:
                raise RuntimeError(f"TwitchDownloader finished but no media in {out_dir}")
            video_out = candidates[0]

        # Fresh empty chat from a prior hung run blocks Overwrite oddly — clear it
        if chat_out.exists() and chat_out.stat().st_size == 0:
            try:
                chat_out.unlink()
            except OSError:
                pass

        # Separate temp folder — shared video cache (stv/bttv) can stall chatdownload
        chat_temp = out_dir / "tmp_chat"
        chat_temp.mkdir(parents=True, exist_ok=True)
        chat_cmd = [
            cli,
            "chatdownload",
            "--id",
            vod_id,
            "-o",
            str(chat_out),
            "--embed-images",
            "false",
            "--bttv",
            "false",
            "--ffz",
            "false",
            "--stv",
            "false",
            "-t",
            threads,
            "--temp-path",
            str(chat_temp),
            "--collision",
            "Overwrite",
            "--banner",
            "false",
            "--log-level",
            "Status,Info,Warning,Error",
        ]
        emit("chat_download_start", output=str(chat_out), threads=threads)
        try:
            # Chat JSON is often 0 bytes until finalize — watch stdout idle, not file size.
            # Busy streams can take a few minutes; a silent hang should not freeze at 58%.
            _run_with_progress(
                chat_cmd,
                "TwitchDownloader chatdownload",
                out_dir,
                on_progress,
                progress_event="chat_download_progress",
                log_event="chat_download_log",
                idle_timeout_s=120.0,
                hard_timeout_s=600.0,
            )
        except RuntimeError as exc:
            if _consume_force_stopped() or "stopped" in str(exc).lower():
                raise
            emit("chat_download_failed", error=str(exc)[:240], output=str(chat_out))
            if chat_out.exists() and chat_out.stat().st_size == 0:
                try:
                    chat_out.unlink()
                except OSError:
                    pass
            return video_out, None

        if not chat_out.exists() or chat_out.stat().st_size == 0:
            emit("chat_download_failed", error="empty chat file", output=str(chat_out))
            return video_out, None

        emit("chat_download_done", output=str(chat_out), bytes=chat_out.stat().st_size)
        return video_out, chat_out
    finally:
        global _active_proc
        _download_busy.clear()
        with _active_proc_lock:
            _active_proc = None


def _reuse_existing_vod(vod_id: str, video_out: Path) -> int | None:
    """Reuse a prior download of the same VOD so retries skip the multi‑minute pull."""
    if video_out.exists() and video_out.stat().st_size > 1_000_000:
        return video_out.stat().st_size
    root = video_out.parent.parent
    if not root.exists():
        return None
    for path in root.glob(f"*/{vod_id}.mp4"):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= 1_000_000:
            continue
        if path.resolve() == video_out.resolve():
            return size
        video_out.parent.mkdir(parents=True, exist_ok=True)
        try:
            if video_out.exists():
                video_out.unlink()
            os_link = getattr(Path, "hardlink_to", None)
            if callable(os_link):
                try:
                    video_out.hardlink_to(path)
                    return size
                except OSError:
                    pass
            shutil.copy2(path, video_out)
            return video_out.stat().st_size
        except OSError:
            continue
    return None


def _run(cmd: list[str], label: str) -> None:
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label} failed: executable not found ({cmd[0]})") from exc

    global _active_proc
    with _active_proc_lock:
        _active_proc = proc
    try:
        out, _ = proc.communicate()
        if proc.returncode != 0:
            if _consume_force_stopped():
                raise RuntimeError("Twitch download stopped")
            detail = (out or "").strip()
            raise RuntimeError(f"{label} failed: {detail or proc.returncode}")
    finally:
        with _active_proc_lock:
            if _active_proc is proc:
                _active_proc = None


def _run_with_progress(
    cmd: list[str],
    label: str,
    watch_dir: Path,
    on_progress: ProgressCb | None,
    *,
    progress_event: str = "video_download_progress",
    log_event: str = "video_download_log",
    idle_timeout_s: float | None = None,
    hard_timeout_s: float | None = None,
) -> None:
    global _active_proc
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

    with _active_proc_lock:
        _active_proc = proc

    stop = threading.Event()
    last_output = time.monotonic()
    started = last_output
    timed_out = False

    def watch_files() -> None:
        nonlocal timed_out
        while not stop.wait(1.5):
            now = time.monotonic()
            if hard_timeout_s is not None and now - started > hard_timeout_s:
                timed_out = True
                try:
                    proc.kill()
                except Exception:
                    pass
                return
            if idle_timeout_s is not None and now - last_output > idle_timeout_s:
                timed_out = True
                try:
                    proc.kill()
                except Exception:
                    pass
                return
            # File-size watch is useful for video parts; chat stays 0 B until finalize
            if progress_event != "video_download_progress":
                continue
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
                    progress_event,
                    {
                        "bytes": total,
                        "bytes_label": _fmt_bytes(total),
                        "newest_file": newest,
                    },
                )

    watcher = threading.Thread(target=watch_files, daemon=True)
    watcher.start()

    lines: list[str] = []
    code = -1
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            text = line.strip()
            if not text:
                continue
            last_output = time.monotonic()
            lines.append(text)
            if not on_progress:
                continue
            percent = _parse_percent(text)
            payload: dict[str, Any] = {"line": text[-240:]}
            if percent is not None:
                payload["percent"] = percent
                on_progress(progress_event, payload)
            elif "%" in text or "Downloading" in text or "STATUS" in text:
                on_progress(log_event, payload)
        code = proc.wait()
    finally:
        stop.set()
        watcher.join(timeout=2)
        with _active_proc_lock:
            if _active_proc is proc:
                _active_proc = None

    if timed_out:
        if _consume_force_stopped():
            raise RuntimeError("Twitch download stopped")
        raise RuntimeError(f"{label} timed out (no progress)")

    if code != 0:
        if _consume_force_stopped():
            raise RuntimeError("Twitch download stopped")
        detail = "\n".join(lines[-20:])
        raise RuntimeError(f"{label} failed: {detail or code}")


def _parse_percent(text: str) -> int | None:
    match = _PERCENT_RE.search(text)
    if not match:
        return None
    value = int(match.group(1))
    return value if 0 <= value <= 100 else None


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