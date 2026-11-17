from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from app.config import settings
from app.models import ChatSpike, ClipCandidate
from app.paths import AUTO_EDITOR_DIR


def ffmpeg_available() -> bool:
    return shutil.which(settings.ffmpeg_bin) is not None


def probe_duration(video_path: Path) -> float | None:
    if not shutil.which(settings.ffprobe_bin):
        return None
    cmd = [
        settings.ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


def spikes_to_candidates(
    spikes: list[ChatSpike],
    *,
    duration: float | None = None,
    pre: float | None = None,
    post: float | None = None,
) -> list[ClipCandidate]:
    pre_s = pre if pre is not None else settings.clip_pre_seconds
    post_s = post if post is not None else settings.clip_post_seconds
    clips: list[ClipCandidate] = []
    for spike in spikes:
        start = max(0.0, spike.peak_second - pre_s)
        end = spike.peak_second + post_s
        if duration is not None:
            end = min(end, duration)
        if end - start < 5:
            continue
        clips.append(
            ClipCandidate(
                id=uuid.uuid4().hex[:10],
                start=round(start, 2),
                end=round(end, 2),
                peak_second=round(spike.peak_second, 2),
                score=round(spike.score, 2),
                sample_messages=spike.sample_messages,
            )
        )
    return clips


def cut_clip(video_path: Path, start: float, end: float, out_path: Path) -> Path:
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg not found on PATH")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.1, end - start)
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video_path),
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"ffmpeg cut failed: {detail[-2000:]}") from exc
    return out_path


def maybe_silence_trim(clip_path: Path) -> Path:
    """
    Uses vendored Auto-Editor:
      vendor/auto-editor → https://github.com/WyattBlue/auto-editor
    """
    out = clip_path.with_name(f"{clip_path.stem}.tight{clip_path.suffix}")

    if shutil.which(settings.auto_editor_bin):
        cmd = [settings.auto_editor_bin, str(clip_path), "--output", str(out), "--no-open"]
    elif AUTO_EDITOR_DIR.exists():
        cmd = [
            sys.executable,
            "-m",
            "auto_editor",
            str(clip_path),
            "--output",
            str(out),
            "--no-open",
        ]
        env_pythonpath = str(AUTO_EDITOR_DIR)
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": env_pythonpath},
            )
            return out if out.exists() else clip_path
        except (subprocess.CalledProcessError, FileNotFoundError):
            return clip_path
    else:
        return clip_path

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return out if out.exists() else clip_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        return clip_path