from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from app.config import settings
from app.paths import GAMING_CLIPPER_DIR, OPENSHORTS_DIR, VERTIFY_CLI
from app.pipeline.clips_studio import (
    clips_studio_available,
    make_vertical_face,
    make_vertical_fit_black,
    make_vertical_fit_blur,
    make_vertical_split,
)
from app.pipeline.layouts import burn_hook_banner, burn_top_explain, hook_text_for_clip


def make_vertical_short(
    clip_path: Path,
    out_path: Path | None = None,
    *,
    width: int | None = None,
    height: int | None = None,
    layout: str = "blur",
    hook_text: str | None = None,
    cam_zoom: float = 1.0,
    game_zoom: float = 1.0,
    game_pan: float | None = None,
) -> Path:
    """
    Turn a landscape clip into a 9:16 Short — vendor renderers only.

    layout:
      blur          — Clips Kitty fit_blur → Vertify → OpenShorts
      full_hook     — Kitty fit_black (full 16:9) + top explain text
      cam_hook_game — Kitty split (cam top) + hook bar
      game_hook_cam — Kitty split (cam bottom) + hook bar
      face          — Kitty track / fit_blur
    """
    out = out_path or clip_path.with_name(f"short_{clip_path.name}")
    out.parent.mkdir(parents=True, exist_ok=True)
    w = width or settings.short_width
    h = height or settings.short_height
    layout_id = (layout or "blur").strip().lower()
    errors: list[str] = []

    if layout_id in {"full_hook", "letterbox_hook", "explain"}:
        if clips_studio_available():
            try:
                plate = make_vertical_fit_black(clip_path, out)
                return _maybe_top_explain(plate, out, hook_text)
            except Exception as exc:
                errors.append(f"ClipsKittyFitBlack: {exc}")
        # Fallback: Gaming-Clipper gaming-split (full plate + title)
        try:
            return _via_gaming_clipper(
                clip_path,
                out,
                hook_text=hook_text,
                cam_zoom=1.0,
                game_pan=None,
                with_cam=False,
            )
        except Exception as exc:
            errors.append(f"GamingClipperPlate: {exc}")
        raise RuntimeError(
            "Full-plate hook Short failed. " + " | ".join(errors)
        )

    if layout_id in {"cam_hook_game", "game_hook_cam"}:
        cam_position = "bottom" if layout_id == "game_hook_cam" else "top"
        # 1) Clips Kitty split renderer (real vendor code)
        if clips_studio_available():
            try:
                result = make_vertical_split(
                    clip_path,
                    out,
                    cam_position=cam_position,
                    cam_zoom=cam_zoom,
                    game_zoom=game_zoom,
                    game_pan=game_pan,
                )
                return _maybe_hook(result["path"], out, hook_text, cam_position)
            except Exception as exc:
                errors.append(f"ClipsKittySplit: {exc}")

        # 2) Gaming-Clipper render_clip (vendor script)
        try:
            return _via_gaming_clipper(
                clip_path,
                out,
                hook_text=hook_text,
                cam_zoom=cam_zoom,
                game_pan=game_pan,
            )
        except Exception as exc:
            errors.append(f"GamingClipper: {exc}")

        raise RuntimeError(
            "Cam/game Short failed — Kitty split and Gaming-Clipper both unavailable. "
            + " | ".join(errors)
        )

    if layout_id == "face" and clips_studio_available():
        try:
            return make_vertical_face(clip_path, out)
        except Exception as exc:
            errors.append(f"KittyFace: {exc}")

    # blur (default) + fallbacks
    if clips_studio_available():
        try:
            return make_vertical_fit_blur(clip_path, out)
        except Exception as exc:
            errors.append(f"ClipsKitty: {exc}")

    try:
        return _via_vertify(clip_path, out, long_edge=max(w, h))
    except Exception as exc:
        errors.append(f"Vertify: {exc}")

    try:
        return _via_openshorts(clip_path, out, w, h)
    except Exception as exc:
        errors.append(f"OpenShorts: {exc}")

    raise RuntimeError(
        "No vertical Shorts engine available. "
        "Run .\\scripts\\fetch-vendor.ps1 (Clips Kitty / Vertify / OpenShorts). "
        + " | ".join(errors)
    )


def openshorts_reframe_available() -> bool:
    return OPENSHORTS_DIR.exists() and (OPENSHORTS_DIR / "reframe_v2.py").exists()


def vertify_available() -> bool:
    return VERTIFY_CLI.exists() or shutil.which("vertify") is not None


def _maybe_hook(
    rendered: Path,
    out: Path,
    hook_text: str | None,
    cam_position: str,
) -> Path:
    """Burn clipper-style hook on the cam/game seam (Kitty has no hook bar)."""
    if not hook_text:
        if rendered.resolve() != out.resolve():
            shutil.copy2(rendered, out)
            return out
        return rendered
    seam = 780 if cam_position != "bottom" else 1140
    staged = out if rendered.resolve() == out.resolve() else rendered
    burned = burn_hook_banner(staged, out, hook_text, seam_y=seam)
    return burned if burned.exists() else staged


def _maybe_top_explain(
    rendered: Path,
    out: Path,
    hook_text: str | None,
) -> Path:
    """White explain title in the top black letterbox."""
    if not hook_text:
        if rendered.resolve() != out.resolve():
            shutil.copy2(rendered, out)
            return out
        return rendered
    staged = out if rendered.resolve() == out.resolve() else rendered
    burned = burn_top_explain(staged, out, hook_text, y=130)
    return burned if burned.exists() else staged


def _via_gaming_clipper(
    clip_path: Path,
    out_path: Path,
    *,
    hook_text: str | None,
    cam_zoom: float,
    game_pan: float | None,
    with_cam: bool = True,
) -> Path:
    """Call vendor/Gaming-Clipper/scripts/render_clip.py for gaming-split + cam."""
    script = GAMING_CLIPPER_DIR / "scripts" / "render_clip.py"
    if not script.exists():
        raise RuntimeError("vendor/Gaming-Clipper missing")

    cam_box = None
    if with_cam:
        from app.pipeline.clips_studio import resolve_split_layout

        layout = resolve_split_layout(clip_path)
        box = layout["webcam_box"]
        # Widen slightly when cam_zoom < 1 (more room) — matches Kitty patch intent
        bx, by, bw, bh = (float(v) for v in box)
        cz = max(0.7, min(1.5, float(cam_zoom or 1.0)))
        if cz != 1.0:
            cx0, cy0 = bx + bw / 2, by + bh / 2
            bw = min(0.45, bw / cz)
            bh = min(0.50, bh / cz)
            bx = max(0.0, min(1.0 - bw, cx0 - bw / 2))
            by = max(0.0, min(1.0 - bh, cy0 - bh / 2))
        cam_box = f"{bx:.4f},{by:.4f},{bw:.4f},{bh:.4f}"

    # Gaming-Clipper needs start/end + analysis.json — for a pre-cut clip use full duration
    from app.pipeline.cutter import probe_duration

    dur = probe_duration(clip_path) or 30.0
    analysis = out_path.with_suffix(".analysis.json")
    analysis.write_text('{"words":[]}', encoding="utf-8")

    cmd = [
        sys.executable,
        str(script),
        "--input",
        str(clip_path),
        "--analysis",
        str(analysis),
        "--start",
        "0",
        "--end",
        f"{dur:.2f}",
        "--layout",
        "gaming-split",
        "--title",
        (hook_text or "CLIP")[:72],
        "--no-snap",
        "--out",
        str(out_path),
    ]
    if cam_box:
        cmd.extend(["--cam-box", cam_box])
    _ = game_pan  # pan is Kitty-native; Gaming-Clipper uses its own game fit
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(GAMING_CLIPPER_DIR),
    )
    analysis.unlink(missing_ok=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail[-2000:] or f"exit {proc.returncode}")
    if not out_path.exists():
        raise RuntimeError("Gaming-Clipper produced no file")
    return out_path


def _via_openshorts(clip_path: Path, out_path: Path, width: int, height: int) -> Path:
    if not openshorts_reframe_available():
        raise RuntimeError("vendor/openshorts missing")

    aspect = width / height
    script = f"""
import sys
sys.path.insert(0, r"{OPENSHORTS_DIR.as_posix()}")
import reframe_v2
reframe_v2.render(
    r"{clip_path.as_posix()}",
    r"{out_path.as_posix()}",
    aspect_ratio={aspect!r},
    force_strategy="GENERAL",
)
print(r"{out_path.as_posix()}")
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(OPENSHORTS_DIR),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail[-2000:] or f"exit {proc.returncode}")
    if not out_path.exists():
        raise RuntimeError("OpenShorts reframe produced no file")
    return out_path


def _via_vertify(clip_path: Path, out_path: Path, *, long_edge: int) -> Path:
    exe = str(VERTIFY_CLI) if VERTIFY_CLI.exists() else shutil.which("vertify")
    if not exe:
        raise RuntimeError("vertify.exe missing — run fetch-vendor.ps1")

    cmd = [
        exe,
        str(clip_path),
        str(out_path),
        "--to",
        "9:16",
        "--fill",
        "blur",
        "--size",
        str(long_edge),
        "--fast",
        "-y",
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
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(detail[-2000:] or str(exc)) from exc
    if not out_path.exists():
        raise RuntimeError("Vertify produced no file")
    return out_path


# re-export for callers that imported hook helper from here historically
__all__ = [
    "make_vertical_short",
    "openshorts_reframe_available",
    "vertify_available",
    "hook_text_for_clip",
]
