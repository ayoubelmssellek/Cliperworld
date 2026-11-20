"""
Glue to ColinGPT9/clips-studio (Clips Kitty) — AGPL-3.0, kept under vendor/.

What we take from it (best-of, not a rewrite):
  - video.cropper fit_blur → battle-tested 9:16 Shorts letterbox
  - video.cropper split → gameplay + facecam stack (cam top/bottom)
  - video.tracker compute_tracking → facecam box / face track
  - analysis.chat_moments  → Twitch chat hype classes (POG / KEKW / CLIP IT)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.paths import CLIPS_STUDIO_DIR

def clips_studio_available() -> bool:
    return CLIPS_STUDIO_DIR.exists() and (CLIPS_STUDIO_DIR / "video" / "cropper.py").exists()


def make_vertical_fit_blur(clip_path: Path, out_path: Path) -> Path:
    """Use Clips Kitty video.cropper.render_vertical(mode=fit_blur)."""
    return _render_vertical(
        clip_path,
        out_path,
        tracking={"mode": "fit_blur", "region": (0.0, 0.0, 1.0, 1.0)},
    )


def make_vertical_fit_black(clip_path: Path, out_path: Path) -> Path:
    """Kitty fit_black — full 16:9 plate on solid black (TikTok letterbox)."""
    return _render_vertical(
        clip_path,
        out_path,
        tracking={"mode": "fit_black", "region": (0.0, 0.0, 1.0, 1.0)},
    )


def resolve_split_layout(clip_path: Path) -> dict:
    """
    Facecam box + gameplay focus for cam/hook/game layouts.
    Uses Kitty YOLO when installed; corner-scores the frame otherwise.
    Never blindly assumes bottom-right cam (that hid LACY's top-left cam).
    """
    from app.pipeline.webcam_detect import detect_webcam_box, median_subject_x

    tracking = _compute_tracking(clip_path) if clips_studio_available() else {}
    kitty_box = None
    path = None
    if tracking.get("mode") == "split" and tracking.get("webcam_box"):
        kitty_box = tuple(float(x) for x in tracking["webcam_box"])
    if tracking.get("mode") == "track":
        path = tracking.get("path")

    box, source = detect_webcam_box(clip_path, kitty_box=kitty_box)
    game_cx = median_subject_x(path, webcam_box=box)
    return {
        "webcam_box": box,
        "game_cx": game_cx,
        "source": source,
        "tracking_mode": tracking.get("mode"),
    }


def resolve_webcam_box(clip_path: Path) -> tuple[float, float, float, float]:
    """Return a normalized facecam box."""
    return resolve_split_layout(clip_path)["webcam_box"]  # type: ignore[return-value]


def make_vertical_split(
    clip_path: Path,
    out_path: Path,
    *,
    cam_position: str = "top",
    cam_zoom: float = 1.0,
    game_zoom: float = 1.0,
    game_pan: float | None = None,
) -> dict:
    """
    Gameplay + facecam stack via Clips Kitty video.cropper.render_vertical(split).
    Detection: StreamCut YuNet / Kitty YOLO / corner score (resolve_split_layout).
    """
    if not clips_studio_available():
        raise RuntimeError("vendor/clips-studio missing")

    layout = resolve_split_layout(clip_path)
    tracking = {"mode": "split", "webcam_box": layout["webcam_box"]}
    auto_cx = float(layout.get("game_cx") or 0.5)
    gpan = float(game_pan) if game_pan is not None else auto_cx
    path = _render_vertical(
        clip_path,
        out_path,
        tracking=tracking,
        cam_position="bottom" if cam_position == "bottom" else "top",
        cam_zoom=cam_zoom,
        game_zoom=game_zoom,
        game_pan=gpan,
    )
    return {
        "path": path,
        "webcam_detected": not str(layout["source"]).startswith("default"),
        "cam_position": cam_position,
        "webcam_box": layout["webcam_box"],
        "source": layout["source"],
        "game_pan": gpan,
    }


def make_vertical_face(clip_path: Path, out_path: Path) -> Path:
    """Follow subject / fit_blur from Kitty tracker; fall back to fit_blur."""
    if not clips_studio_available():
        raise RuntimeError("vendor/clips-studio missing")
    tracking = _compute_tracking(clip_path)
    if tracking.get("mode") == "split":
        # Face preset wants a single subject crop, not stack
        tracking = {"mode": "fit_blur", "region": (0.0, 0.0, 1.0, 1.0)}
    if tracking.get("mode") not in {"track", "fit_blur"}:
        tracking = {"mode": "fit_blur", "region": (0.0, 0.0, 1.0, 1.0)}
    return _render_vertical(clip_path, out_path, tracking=tracking)


def _compute_tracking(clip_path: Path) -> dict:
    """Run Clips Kitty YOLO tracker (may download yolov8n-pose on first use)."""
    script = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, r"{CLIPS_STUDIO_DIR.as_posix()}")
from video.tracker import compute_tracking
result = compute_tracking(Path(r"{clip_path.as_posix()}"), sample_fps=4.0)
# JSON-safe
mode = result.get("mode")
out = {{"mode": mode}}
if mode == "split":
    box = result.get("webcam_box")
    out["webcam_box"] = [float(x) for x in box] if box else None
elif mode == "fit_blur":
    region = result.get("region")
    out["region"] = [float(x) for x in region] if region else None
elif mode == "track":
    path = result.get("path") or []
    out["path"] = [[float(t), float(x)] for t, x in path]
    if result.get("face_y") is not None:
        out["face_y"] = float(result["face_y"])
print(json.dumps(out))
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(CLIPS_STUDIO_DIR),
            timeout=300,
        )
    except Exception:
        return {"mode": "fit_blur", "region": (0.0, 0.0, 1.0, 1.0)}
    if proc.returncode != 0:
        return {"mode": "fit_blur", "region": (0.0, 0.0, 1.0, 1.0)}
    try:
        line = (proc.stdout or "").strip().splitlines()[-1]
        data = json.loads(line)
    except Exception:
        return {"mode": "fit_blur", "region": (0.0, 0.0, 1.0, 1.0)}
    mode = data.get("mode")
    if mode == "split" and data.get("webcam_box"):
        box = data["webcam_box"]
        return {"mode": "split", "webcam_box": tuple(float(x) for x in box)}
    if mode == "fit_blur":
        region = data.get("region")
        return {
            "mode": "fit_blur",
            "region": tuple(float(x) for x in region) if region else (0.0, 0.0, 1.0, 1.0),
        }
    if mode == "track":
        path = [(float(t), float(x)) for t, x in (data.get("path") or [])]
        out: dict = {"mode": "track", "path": path or [(0.0, 0.5)]}
        if data.get("face_y") is not None:
            out["face_y"] = float(data["face_y"])
        return out
    return {"mode": "fit_blur", "region": (0.0, 0.0, 1.0, 1.0)}


def _render_vertical(
    clip_path: Path,
    out_path: Path,
    *,
    tracking: dict,
    cam_position: str = "top",
    cam_zoom: float = 1.0,
    game_zoom: float = 1.0,
    game_pan: float = 0.5,
) -> Path:
    if not clips_studio_available():
        raise RuntimeError("vendor/clips-studio missing")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tracking_json = json.dumps(tracking)
    script = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, r"{CLIPS_STUDIO_DIR.as_posix()}")
from video.cropper import render_vertical
tracking = json.loads({tracking_json!r})
if tracking.get("mode") == "split" and tracking.get("webcam_box"):
    tracking["webcam_box"] = tuple(tracking["webcam_box"])
if tracking.get("mode") in {"fit_blur", "fit_black"} and tracking.get("region"):
    tracking["region"] = tuple(tracking["region"])
if tracking.get("mode") == "track" and tracking.get("path"):
    tracking["path"] = [(float(t), float(x)) for t, x in tracking["path"]]
render_vertical(
    Path(r"{clip_path.as_posix()}"),
    tracking,
    Path(r"{out_path.as_posix()}"),
    cam_position={cam_position!r},
    cam_zoom={float(cam_zoom)!r},
    game_zoom={float(game_zoom)!r},
    game_pan={float(game_pan)!r},
)
print(r"{out_path.as_posix()}")
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(CLIPS_STUDIO_DIR),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail[-2000:] or f"exit {proc.returncode}")
    if not out_path.exists():
        raise RuntimeError("Clips Kitty render produced no file")
    return out_path


def chat_hype_events(
    messages: list[tuple[float, str, str]],
    duration: float,
) -> list[dict]:
    """
    Run Clips Kitty chat_moments on [(offset, author, text)].
    Returns event dicts: {second, label, score_hint}.
    """
    if not clips_studio_available() or not messages or duration <= 0:
        return []

    import tempfile

    payload = {
        "duration": duration,
        "messages": [[t, who, text] for t, who, text in messages],
    }
    with tempfile.TemporaryDirectory(prefix="cw_kitty_chat_") as tmp:
        payload_path = Path(tmp) / "payload.json"
        out_path = Path(tmp) / "events.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        script = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, r"{CLIPS_STUDIO_DIR.as_posix()}")
import yaml
from analysis.chat_moments import chat_signal

payload = json.loads(Path(r"{payload_path.as_posix()}").read_text(encoding="utf-8"))
cfg = yaml.safe_load(Path(r"{(CLIPS_STUDIO_DIR / "config" / "gaming.yaml").as_posix()}").read_text(encoding="utf-8")) or {{}}
sig = chat_signal(
    [(float(t), str(who), str(text)) for t, who, text in payload["messages"]],
    float(payload["duration"]),
    cfg.get("chat_classes") or {{}},
    lag=float(cfg.get("chat_lag_seconds") or 6),
    ignore=cfg.get("chat_ignore") or [],
)
out = []
if sig:
    for item in (sig.events or []):
        second = float(item[0])
        label = str(item[1])
        hint = float(item[2]) if len(item) > 2 else 1.0
        out.append({{"second": second, "label": label, "score_hint": hint}})
Path(r"{out_path.as_posix()}").write_text(json.dumps(out), encoding="utf-8")
print(len(out))
"""
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(CLIPS_STUDIO_DIR),
                timeout=120,
            )
        except Exception:
            return []
        if proc.returncode != 0 or not out_path.exists():
            return []
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
