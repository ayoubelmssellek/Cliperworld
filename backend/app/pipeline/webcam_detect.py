"""Find Twitch-style facecam overlays without guessing bottom-right.

Uses Clips Kitty YOLO when available; otherwise scores the four corners
with OpenCV (PiP overlays sit in a corner and look unlike the game plate).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

# Normalized (x, y, w, h) — typical Twitch overlay slots
_CORNER_CANDIDATES: list[tuple[float, float, float, float]] = [
    (0.01, 0.02, 0.24, 0.32),  # top-left (LACY, many variety streamers)
    (0.74, 0.02, 0.24, 0.32),  # top-right
    (0.01, 0.62, 0.28, 0.36),  # bottom-left
    (0.70, 0.58, 0.28, 0.40),  # bottom-right (classic Fortnite/Warzone)
]


def is_corner_overlay(box: tuple[float, float, float, float]) -> bool:
    """Reject center-of-frame boxes (those are game subjects, not webcam)."""
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    area = w * h
    if area < 0.03 or area > 0.22:
        return False
    if w > 0.45 or h > 0.55:
        return False
    near_left = cx < 0.38
    near_right = cx > 0.62
    near_top = cy < 0.42
    near_bottom = cy > 0.55
    return (near_left or near_right) and (near_top or near_bottom)


def detect_webcam_box(
    clip_path: Path,
    *,
    kitty_box: tuple[float, float, float, float] | None = None,
) -> tuple[tuple[float, float, float, float], str]:
    """
    Return (box, source).
    Order: StreamCut YuNet inset → Kitty split → corner score → top-left default.
    """
    # 1) StreamCut (YuNet + stationary inset — best for gaming PiP)
    try:
        from app.pipeline.streamcut_facecam import detect_facecam_box, streamcut_available

        if streamcut_available():
            hit = detect_facecam_box(Path(clip_path))
            if hit and hit.get("box") and is_corner_overlay(hit["box"]):
                return hit["box"], f"streamcut:{hit.get('corner') or 'auto'}"
    except Exception:
        pass

    box: tuple[float, float, float, float] | None = None
    source = "default_tl"
    if kitty_box and is_corner_overlay(kitty_box):
        box = (float(kitty_box[0]), float(kitty_box[1]), float(kitty_box[2]), float(kitty_box[3]))
        source = "kitty"
    else:
        scored = score_corner_candidates(clip_path)
        if scored and scored[0][1] >= 0.35:
            box, _score = scored[0]
            source = "corner"
    if box is None:
        box = _CORNER_CANDIDATES[0]
    tightened = tighten_box_to_face(clip_path, box)
    if tightened:
        return tightened, f"{source}+face"
    return box, source


def tighten_box_to_face(
    clip_path: Path,
    box: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    """Zoom the PiP onto the streamer's face when OpenCV finds one inside it."""
    frames = _sample_frames(clip_path, n=4)
    if not frames:
        return None
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not cascade_path.exists():
        return None
    cascade = cv2.CascadeClassifier(str(cascade_path))
    faces: list[tuple[float, float, float, float]] = []
    for frame in frames:
        h, w = frame.shape[:2]
        x, y, bw, bh = box
        x0, y0 = int(x * w), int(y * h)
        x1, y1 = int((x + bw) * w), int((y + bh) * h)
        roi = frame[y0:y1, x0:x1]
        if roi.size == 0:
            continue
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        found = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(28, 28))
        for fx, fy, fw, fh in found:
            # Map back to full-frame normalized, pad around face
            abs_x = x0 + fx
            abs_y = y0 + fy
            pad = 0.35
            nx = max(0.0, (abs_x - fw * pad) / w)
            ny = max(0.0, (abs_y - fh * pad * 1.2) / h)
            nw = min(1.0 - nx, (fw * (1 + 2 * pad)) / w)
            nh = min(1.0 - ny, (fh * (1 + 2.4 * pad)) / h)
            # Keep inside original PiP so we don't pull in gameplay
            nx = max(nx, x)
            ny = max(ny, y)
            nw = min(nw, x + bw - nx)
            nh = min(nh, y + bh - ny)
            if nw >= 0.10 and nh >= 0.12:
                faces.append((nx, ny, nw, nh))
    if not faces:
        return None
    # Median face window
    arr = np.array(faces)
    return (
        round(float(np.median(arr[:, 0])), 4),
        round(float(np.median(arr[:, 1])), 4),
        round(float(np.median(arr[:, 2])), 4),
        round(float(np.median(arr[:, 3])), 4),
    )


def score_corner_candidates(
    clip_path: Path,
) -> list[tuple[tuple[float, float, float, float], float]]:
    frames = _sample_frames(clip_path, n=5)
    if not frames:
        return []

    ranked: list[tuple[tuple[float, float, float, float], float]] = []
    for box in _CORNER_CANDIDATES:
        scores = [_score_region(frame, box) for frame in frames]
        ranked.append((box, float(np.median(scores))))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def median_subject_x(
    path: list[tuple[float, float]] | None,
    *,
    webcam_box: tuple[float, float, float, float] | None = None,
) -> float:
    """Horizontal focus for the gameplay band (0..1). Avoid the webcam side."""
    xs = [float(x) for _, x in (path or []) if 0.0 <= float(x) <= 1.0]
    if xs:
        cx = float(np.median(xs))
    else:
        cx = 0.5
    if webcam_box and is_corner_overlay(webcam_box):
        wx = webcam_box[0] + webcam_box[2] / 2
        # Cam top-left → keep prompts/UI on the right in frame; cam BR → bias left
        if wx < 0.4:
            cx = max(cx, 0.58)
        elif wx > 0.6:
            cx = min(cx, 0.42)
    return max(0.22, min(0.78, cx))


def _sample_frames(clip_path: Path, n: int = 5) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        return []
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) or 30.0
        if total <= 0:
            # time-based samples across ~first 20s
            times = [0.5 + i * 3.0 for i in range(n)]
            frames = []
            for t in times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if ok and frame is not None:
                    frames.append(frame)
            return frames
        idxs = [int(total * (i + 1) / (n + 1)) for i in range(n)]
        frames = []
        for idx in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
        return frames
    finally:
        cap.release()


def _score_region(frame: np.ndarray, box: tuple[float, float, float, float]) -> float:
    """Higher = more likely a facecam PiP (structured, colorful, edged)."""
    h, w = frame.shape[:2]
    x, y, bw, bh = box
    x0, y0 = int(x * w), int(y * h)
    x1, y1 = int((x + bw) * w), int((y + bh) * h)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return 0.0
    roi = frame[y0:y1, x0:x1]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    # Edge density — overlays have borders / face detail
    edges = cv2.Canny(gray, 60, 140)
    edge_score = float(edges.mean()) / 40.0
    # Contrast
    contrast = float(gray.std()) / 60.0
    # Skin-ish chroma (YCrCb Cr channel peaks for faces)
    ycrcb = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)
    cr = ycrcb[:, :, 1]
    skin = cv2.inRange(cr, 133, 173)
    skin_score = float(skin.mean()) / 80.0
    # Prefer regions that differ from the rest of the frame (PiP vs game)
    full_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    diff = abs(float(gray.mean()) - float(full_gray.mean())) / 50.0
    return edge_score * 0.35 + contrast * 0.25 + skin_score * 0.30 + diff * 0.10
