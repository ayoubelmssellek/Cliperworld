"""
Glue to xAmirHamza77/StreamCut facecam detection (MIT).

Uses their bundled YuNet ONNX + stationary-inset classifier so we find
top-left / bottom-right cams and ignore in-game faces (the LACY bug).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from app.paths import STREAMCUT_DIR


def streamcut_available() -> bool:
    return (
        STREAMCUT_DIR.exists()
        and (STREAMCUT_DIR / "studio" / "face_layout.py").exists()
        and (STREAMCUT_DIR / "studio" / "models" / "face_detection_yunet_2023mar.onnx").exists()
    )


def detect_facecam_box(clip_path: Path) -> dict[str, Any] | None:
    """
    Return {box: (x,y,w,h) normalized, corner, source} or None.
    Calls StreamCut plan_gamer_split on the whole clip.
    """
    if not streamcut_available():
        return None
    clip_path = Path(clip_path)
    if not clip_path.exists():
        return None

    # Import StreamCut's package without installing it
    root = str(STREAMCUT_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from studio.face_layout import plan_gamer_split
        import cv2
    except Exception:
        return None

    try:
        cap = cv2.VideoCapture(str(clip_path))
        if not cap.isOpened():
            return None
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()
        if src_w <= 0 or src_h <= 0 or src_w <= src_h:
            return None
        duration = frames / fps if frames > 0 else 30.0
        plan = plan_gamer_split(
            clip_path,
            start=0.0,
            end=min(duration, 45.0),
            src_w=src_w,
            src_h=src_h,
            cam_pos="auto",
        )
    except Exception:
        return None

    if not plan or not plan.get("cam"):
        return None
    cam = plan["cam"]
    box = (
        round(float(cam["x"]) / src_w, 4),
        round(float(cam["y"]) / src_h, 4),
        round(float(cam["w"]) / src_w, 4),
        round(float(cam["h"]) / src_h, 4),
    )
    return {
        "box": box,
        "corner": plan.get("corner"),
        "source": "streamcut",
        "plan": plan,
        "src_w": src_w,
        "src_h": src_h,
    }
