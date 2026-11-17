from __future__ import annotations

import subprocess
from pathlib import Path

from app.config import settings
from app.models import ChatSpike
from app.pipeline.cutter import ffmpeg_available


def detect_audio_spikes(
    video_path: Path,
    *,
    max_spikes: int | None = None,
    window_seconds: float = 8.0,
) -> list[ChatSpike]:
    """
    Fallback when YouTube has no live chat: find loud moments with ffmpeg astats.
    """
    if not ffmpeg_available():
        return []

    limit = max_spikes if max_spikes is not None else settings.max_clips
    # Sample volume every window using silencedetect inverted heuristic via volumedetect chunks is heavy.
    # Use astats over time with showinfo-like approach: extract RMS via ffmpeg + python.
    cmd = [
        settings.ffmpeg_bin,
        "-i",
        str(video_path),
        "-af",
        f"asetnsamples=n={int(48000 * window_seconds)},astats=metadata=1:reset=1",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        return []

    rms_values: list[tuple[float, float]] = []
    t = 0.0
    for line in (proc.stderr or "").splitlines():
        if "RMS_level" in line or "RMS level" in line:
            # Examples: lavfi.astats.Overall.RMS_level=-20.1  OR  RMS level dB: -20.12
            num = None
            for part in line.replace("=", " ").replace(":", " ").split():
                try:
                    val = float(part)
                    if -120 <= val <= 0:
                        num = val
                        break
                except ValueError:
                    continue
            if num is not None:
                rms_values.append((t, num))
                t += window_seconds

    if len(rms_values) < 4:
        return _even_fallback(video_path, limit)

    levels = [v for _, v in rms_values]
    # Louder = higher (less negative). Use percentile threshold.
    ordered = sorted(levels)
    threshold = ordered[int(len(ordered) * 0.85)]
    raw: list[ChatSpike] = []
    for peak, level in rms_values:
        if level < threshold:
            continue
        score = float(level - ordered[len(ordered) // 2] + 10)
        raw.append(
            ChatSpike(
                peak_second=peak + window_seconds / 2,
                score=max(1.0, score),
                message_count=0,
                sample_messages=["[audio spike]"],
            )
        )

    raw.sort(key=lambda s: s.score, reverse=True)
    selected: list[ChatSpike] = []
    min_gap = settings.clip_pre_seconds + settings.clip_post_seconds
    for spike in raw:
        if any(abs(spike.peak_second - kept.peak_second) < min_gap for kept in selected):
            continue
        selected.append(spike)
        if len(selected) >= limit:
            break
    selected.sort(key=lambda s: s.peak_second)
    return selected or _even_fallback(video_path, limit)


def _even_fallback(video_path: Path, limit: int) -> list[ChatSpike]:
    from app.pipeline.cutter import probe_duration

    duration = probe_duration(video_path) or 0
    if duration < 20:
        return []
    # Take evenly spaced moments from middle sections
    count = min(limit, max(1, int(duration // 180)))
    spikes: list[ChatSpike] = []
    for i in range(count):
        peak = duration * (i + 1) / (count + 1)
        spikes.append(
            ChatSpike(
                peak_second=peak,
                score=1.0,
                message_count=0,
                sample_messages=["[auto segment]"],
            )
        )
    return spikes