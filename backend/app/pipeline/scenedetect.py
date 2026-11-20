from __future__ import annotations

"""
Uses vendored PySceneDetect:
  vendor/PySceneDetect → https://github.com/Breakthrough/PySceneDetect

Only scan a short window around each clip — full-VOD scene detect per clip
was what made Cut take forever (N full-file scans).
"""

import sys
from pathlib import Path

from app.paths import PYSCENEDETECT_DIR


def snap_to_scenes(video_path: Path, start: float, end: float) -> tuple[float, float]:
    if PYSCENEDETECT_DIR.exists():
        sys.path.insert(0, str(PYSCENEDETECT_DIR))

    try:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import ContentDetector
    except ImportError:
        return start, end

    pad = 8.0
    seek_start = max(0.0, float(start) - pad)
    seek_end = float(end) + pad
    if seek_end <= seek_start + 1:
        return start, end

    try:
        video = open_video(str(video_path))
        video.seek(seek_start)
        manager = SceneManager()
        manager.add_detector(ContentDetector())
        manager.detect_scenes(video, end_time=seek_end)
        scenes = manager.get_scene_list()
    except Exception:
        return start, end

    if not scenes:
        return start, end

    cuts = [seek_start] + [scene[0].get_seconds() for scene in scenes] + [seek_end]
    new_start = start
    new_end = end
    for cut in cuts:
        if start - 3 <= cut <= start:
            new_start = cut
        if end <= cut <= end + 3:
            new_end = cut
    return new_start, max(new_end, new_start + 5)
