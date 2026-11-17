from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.config import settings
from app.paths import OPENSHORTS_DIR, WHISPERX_DIR


def caption_clip(clip_path: Path, job_dir: Path) -> Path | None:
    """
    Caption using vendored repos:
      1) OpenShorts subtitles.py (vendor/openshorts)
      2) WhisperX from vendor/whisperX (if installed)
    """
    result = _try_openshorts_subtitles(clip_path, job_dir)
    if result:
        return result

    if settings.whisperx_enabled:
        result = _try_whisperx(clip_path, job_dir)
        if result:
            return result
    return None


def _try_openshorts_subtitles(clip_path: Path, job_dir: Path) -> Path | None:
    """
    Uses OpenShorts' own subtitle module from the cloned repo.
    https://github.com/mutonby/openshorts
    """
    if not OPENSHORTS_DIR.exists():
        return None

    # Generate SRT via whisperx/faster-whisper if available, else skip burn
    srt = _transcribe_to_srt(clip_path, job_dir)
    if not srt:
        return None

    out = job_dir / f"subtitled_{clip_path.name}"
    script = f"""
import sys
sys.path.insert(0, r"{OPENSHORTS_DIR.as_posix()}")
import subtitles
subtitles.burn_subtitles(
    r"{clip_path.as_posix()}",
    r"{srt.as_posix()}",
    r"{out.as_posix()}",
)
print(r"{out.as_posix()}")
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(OPENSHORTS_DIR),
        )
        path = Path(proc.stdout.strip().splitlines()[-1])
        return path if path.exists() else (out if out.exists() else None)
    except (subprocess.CalledProcessError, IndexError, OSError):
        return None


def _transcribe_to_srt(clip_path: Path, job_dir: Path) -> Path | None:
    out_dir = job_dir / "transcript"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Prefer vendored WhisperX if importable
    if WHISPERX_DIR.exists():
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            str(WHISPERX_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        )
        cmd = [
            sys.executable,
            "-m",
            "whisperx",
            str(clip_path),
            "--output_dir",
            str(out_dir),
            "--output_format",
            "srt",
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
            srt_files = list(out_dir.glob("*.srt"))
            if srt_files:
                return srt_files[0]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    # Fallback: faster-whisper CLI style via OpenShorts deps if present
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return None

    try:
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(clip_path))
        srt_path = out_dir / f"{clip_path.stem}.srt"
        lines: list[str] = []
        for i, seg in enumerate(segments, start=1):
            lines.append(str(i))
            lines.append(f"{_ts(seg.start)} --> {_ts(seg.end)}")
            lines.append(seg.text.strip())
            lines.append("")
        srt_path.write_text("\n".join(lines), encoding="utf-8")
        return srt_path
    except Exception:
        return None


def _try_whisperx(clip_path: Path, job_dir: Path) -> Path | None:
    srt = _transcribe_to_srt(clip_path, job_dir)
    if not srt:
        return None
    captioned = job_dir / f"captioned_{clip_path.name}"
    vf = f"subtitles={srt.as_posix().replace(':', '\\\\:')}"
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(clip_path),
        "-vf",
        vf,
        "-c:a",
        "copy",
        str(captioned),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return captioned if captioned.exists() else None
    except subprocess.CalledProcessError:
        return None


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"