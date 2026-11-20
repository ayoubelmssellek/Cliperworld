"""Shorts layout helpers — cam/game stack + hook banner.

Framing follows Auto-Clipper / Gaming-Clipper / StreamCut patterns:
  - cam band: crop detected PiP (with side pad) → lanczos fill
  - game band: fit-width on blur, or cover-crop toward game_cx when zoomed
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from app.config import settings

# Matches Clips Kitty CAM_H seam on 1080x1920 (~40/60 split)
SEAM_Y = 780
HOOK_BOX_H = 110
CAM_H = 780
GAME_H = 1920 - CAM_H  # 1140


def windows_font_file() -> Path | None:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for name in ("arial.ttf", "ARIAL.TTF", "segoeui.ttf", "calibri.ttf", "tahoma.ttf"):
        path = windir / "Fonts" / name
        if path.exists():
            return path
    return None


def burn_top_explain(
    video_path: Path,
    out_path: Path,
    text: str,
    *,
    y: int = 120,
) -> Path:
    """
    White explain/hook text in the top black letterbox (TikTok full-plate style).
    No white box — just large centered title on black.
    """
    hook = _clean_hook(text)
    if not hook:
        return video_path

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Prefer ~2 short lines for long explains
    words = hook.split()
    if len(hook) > 36 and len(words) > 4:
        mid = max(1, len(words) // 2)
        line1 = " ".join(words[:mid])[:48]
        line2 = " ".join(words[mid:])[:48]
        lines = [line1, line2]
    else:
        lines = [hook[:56]]

    font = windows_font_file()
    font_arg = "font=Arial:"
    if font is not None:
        font_esc = str(font).replace("\\", "/").replace(":", "\\\\:")
        font_arg = f"fontfile={font_esc}:"

    parts: list[str] = []
    line_h = 58
    start_y = max(40, y - (len(lines) - 1) * line_h // 2)
    for i, line in enumerate(lines):
        safe = _escape_drawtext(line)
        parts.append(
            f"drawtext={font_arg}text='{safe}':"
            f"fontcolor=white:fontsize=48:"
            f"x=(w-text_w)/2:y={start_y + i * line_h}:"
            f"borderw=3:bordercolor=black@0.55"
        )
    vf = ",".join(parts)
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError:
        return video_path
    return out_path if out_path.exists() and out_path.stat().st_size > 0 else video_path


def burn_hook_banner(
    video_path: Path,
    out_path: Path,
    text: str,
    *,
    seam_y: int = SEAM_Y,
) -> Path:
    """
    White title bar across the cam/game seam (clipper-style hook).
    """
    hook = _clean_hook(text)
    if not hook:
        return video_path

    out_path.parent.mkdir(parents=True, exist_ok=True)
    box_y = max(0, seam_y - HOOK_BOX_H // 2)
    safe = _escape_drawtext(hook)
    if len(safe) > 72:
        safe = safe[:69].rstrip() + "..."

    font = windows_font_file()
    # Windows ffmpeg drops a single \ before :, so the filter needs C\\:/Fonts/...
    font_arg = "font=Arial:"
    if font is not None:
        font_esc = str(font).replace("\\", "/").replace(":", "\\\\:")
        font_arg = f"fontfile={font_esc}:"

    vf = (
        f"drawbox=x=40:y={box_y}:w=iw-80:h={HOOK_BOX_H}:"
        f"color=white@0.94:t=fill,"
        f"drawtext={font_arg}text='{safe}':"
        f"fontcolor=black:fontsize=42:"
        f"x=(w-text_w)/2:y={box_y}+({HOOK_BOX_H}-text_h)/2"
    )
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError:
        return video_path
    return out_path if out_path.exists() and out_path.stat().st_size > 0 else video_path


def clamp_zoom(value: float | None, *, lo: float = 0.7, hi: float = 1.5, default: float = 1.0) -> float:
    try:
        z = float(value) if value is not None else default
    except (TypeError, ValueError):
        z = default
    return max(lo, min(hi, z))


def pad_webcam_box(
    box: tuple[float, float, float, float],
    *,
    zoom: float = 1.0,
) -> tuple[float, float, float, float]:
    """
    Expand the detected PiP so the cam band shows room around the streamer.

    Side pad is intentionally wider than top/bottom (user framing).
    zoom > 1 → tighter on the face; zoom < 1 → even more context.
    """
    x, y, w, h = (float(v) for v in box)
    z = clamp_zoom(zoom)
    # More side room than before; widen further when zoomed out.
    side = (0.045 + w * 0.20) / z
    top = (0.035 + h * 0.12) / z
    bot = (0.025 + h * 0.10) / z
    side = min(side, 0.08)
    top = min(top, 0.06)
    bot = min(bot, 0.05)

    nx = max(0.0, x - side)
    ny = max(0.0, y - top)
    nw = min(1.0 - nx, w + 2 * side)
    nh = min(1.0 - ny, h + top + bot)

    # Cap so we never swallow half the gameplay into the cam band.
    max_w = 0.44 if z <= 1.0 else 0.38
    max_h = 0.46 if z <= 1.0 else 0.40
    nw = min(nw, max_w, 1.0 - nx)
    nh = min(nh, max_h, 1.0 - ny)

    # If zoomed in, shrink around the padded center.
    if z > 1.0:
        cx = nx + nw / 2
        cy = ny + nh / 2
        nw = max(0.14, nw / z)
        nh = max(0.18, nh / z)
        nx = max(0.0, min(1.0 - nw, cx - nw / 2))
        ny = max(0.0, min(1.0 - nh, cy - nh / 2))

    nw = max(min(nw, 1.0 - nx), 0.14)
    nh = max(min(nh, 1.0 - ny), 0.18)
    return (round(nx, 4), round(ny, 4), round(nw, 4), round(nh, 4))


def render_cam_game_stack(
    clip_path: Path,
    out_path: Path,
    webcam_box: tuple[float, float, float, float],
    *,
    cam_position: str = "top",
    hook_text: str | None = None,
    game_cx: float = 0.5,
    cam_zoom: float = 1.0,
    game_zoom: float = 1.0,
) -> Path:
    """
    Facecam + gameplay stack (Auto-Clipper / StreamCut / Gaming-Clipper):
      - cam band: padded PiP filled to 1080x672
      - game band: ALWAYS cover-fill the phone slot (never letterbox the whole
        16:9 stream — that made a tiny nested stream under the hook).
        game_zoom digs into gameplay; game_cx pans left/right.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cz = clamp_zoom(cam_zoom)
    # 1.0 = fill phone game area; up to 2.0 = dig into the action
    gz = clamp_zoom(game_zoom, lo=1.0, hi=2.0, default=1.0)
    bx, by, bw, bh = pad_webcam_box(webcam_box, zoom=cz)
    gcx = max(0.05, min(0.95, float(game_cx or 0.5)))

    # Desk cams sit low in the PiP — bias fill crop downward. No darken on cam.
    cam_chain = (
        f"[0:v]crop=iw*{bw:.4f}:ih*{bh:.4f}:iw*{bx:.4f}:ih*{by:.4f},"
        f"scale=1080:{CAM_H}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop=1080:{CAM_H}:(iw-1080)/2:max(0\\,ih-{CAM_H}),"
        f"unsharp=5:5:0.6:5:5:0.0,setsar=1[cam]"
    )

    # Cover-fill gameplay (Auto-Clipper game_rect) — fills the phone slot.
    # Pan (gcx) + zoom (gz) choose WHICH part of the game you see — not a
    # letterboxed mini of the whole stream (that caused the nested look).
    game_chain = (
        f"[0:v]scale=1080:{GAME_H}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"scale=iw*{gz:.4f}:ih*{gz:.4f},"
        f"crop=1080:{GAME_H}:"
        f"max(0\\,min(iw-1080\\,(iw-1080)*{gcx:.4f})):"
        f"max(0\\,(ih-{GAME_H})/2),"
        f"unsharp=5:5:0.4:5:5:0.0,setsar=1[game]"
    )

    stack = "[game][cam]" if cam_position == "bottom" else "[cam][game]"
    filters = f"{cam_chain};{game_chain};{stack}vstack=inputs=2[v]"

    staged = out_path.with_name(f"{out_path.stem}_stack{out_path.suffix}")
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(clip_path),
        "-filter_complex",
        filters,
        "-map",
        "[v]",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(staged),
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "")[-1200:]
        raise RuntimeError(f"cam/game stack render failed: {detail}") from exc
    if not staged.exists() or staged.stat().st_size == 0:
        raise RuntimeError("cam/game stack render failed")

    seam = SEAM_Y if cam_position != "bottom" else GAME_H
    if hook_text:
        burned = burn_hook_banner(staged, out_path, hook_text, seam_y=seam)
        if burned == out_path and out_path.exists():
            staged.unlink(missing_ok=True)
            return out_path
    staged.replace(out_path)
    return out_path


def hook_text_for_clip(
    *,
    title: str | None,
    hook: str | None,
    samples: list[str] | None,
    streamer: str | None = None,
) -> str:
    # Punchy chat samples first, then clean hook/title — skip Gemma clickbait.
    for sample in samples or []:
        text = str(sample or "").strip()
        if text and not text.upper().startswith("CHAT:") and not _bad_hook(text):
            return text[:48]
    for candidate in (hook, title):
        text = str(candidate or "").strip()
        if text and not _bad_hook(text):
            return text[:72]
    if streamer:
        return f"{streamer.upper()} HIGHLIGHT"
    return "CLIP THIS"


def _bad_hook(text: str) -> bool:
    low = text.lower()
    markers = (
        "unbelievable",
        "secrets revealed",
        "you won't believe",
        "gone wrong",
        "viral",
        "snap scrolling",
        "let me fuck",
        "stalking me",
    )
    return any(m in low for m in markers) or len(text) > 70


def _clean_hook(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = text.replace("\n", " ")
    return text[:90]


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\u2019")
        .replace("%", "%%")
    )
