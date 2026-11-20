from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from pydantic import ValidationError

from app.config import settings
from app.models import Job, JobStatus, Platform
from app.pipeline.detect import normalize_input_url
from app.pipeline.quality import normalize_quality, quality_label

_lock = threading.RLock()


def _job_path(job_id: str) -> Path:
    return settings.data_dir / "jobs" / f"{job_id}.json"


def _normalize_layout(layout: str | None) -> str:
    key = (layout or "blur").strip().lower()
    allowed = {"blur", "full_hook", "letterbox_hook", "explain", "cam_hook_game", "game_hook_cam", "face"}
    if key in {"letterbox_hook", "explain"}:
        return "full_hook"
    return key if key in allowed else "blur"


def _clamp_zoom(value: float | None, *, lo: float, hi: float, default: float) -> float:
    try:
        z = float(value) if value is not None else default
    except (TypeError, ValueError):
        z = default
    return max(lo, min(hi, z))


def create_job(
    url: str,
    *,
    max_clips: int,
    with_captions: bool,
    quality: str = "720",
    with_gemma: bool = True,
    layout: str = "blur",
    cam_zoom: float = 1.0,
    game_zoom: float = 1.0,
    game_pan: float = 0.55,
) -> Job:
    try:
        resolved_url, platform, resolve_meta = normalize_input_url(url)
    except ValueError:
        raise
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc

    q = normalize_quality(quality)
    layout_id = _normalize_layout(layout)
    cam_z = _clamp_zoom(cam_zoom, lo=0.7, hi=1.5, default=1.0)
    game_z = _clamp_zoom(game_zoom, lo=1.0, hi=2.0, default=1.0)
    game_p = _clamp_zoom(game_pan, lo=0.0, hi=1.0, default=0.55)
    now = time.time()
    meta: dict = {
        "quality_label": quality_label(q),
        "layout": layout_id,
        "cam_zoom": cam_z,
        "game_zoom": game_z,
        "game_pan": game_p,
    }
    if resolve_meta:
        meta["resolve"] = resolve_meta
    job = Job(
        id=uuid.uuid4().hex[:12],
        url=resolved_url,
        platform=platform,
        status=JobStatus.queued,
        message=(
            f"Resolved channel → latest VOD {resolve_meta.get('vod_id')}"
            if resolve_meta.get("resolved_from_channel")
            else "Queued"
        ),
        with_captions=with_captions,
        with_gemma=with_gemma,
        max_clips=max_clips,
        quality=q,
        layout=layout_id,
        cam_zoom=cam_z,
        game_zoom=game_z,
        game_pan=game_p,
        created_at=now,
        updated_at=now,
        meta=meta,
        vod_id=resolve_meta.get("vod_id"),
    )
    save_job(job)
    return job


def save_job(job: Job) -> None:
    """Atomic write so readers never see empty/partial JSON."""
    job.updated_at = time.time()
    path = _job_path(job.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = job.model_dump_json(indent=2)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    with _lock:
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


def get_job(job_id: str) -> Job | None:
    path = _job_path(job_id)
    if not path.exists():
        return None

    # Retry briefly — another thread may be mid-replace
    last_error: Exception | None = None
    for _ in range(8):
        with _lock:
            try:
                raw = path.read_text(encoding="utf-8").strip()
                if not raw:
                    time.sleep(0.02)
                    continue
                return Job.model_validate_json(raw)
            except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
        time.sleep(0.03)

    if last_error:
        # Keep API alive; treat unreadable job as missing for this poll
        return None
    return None


def list_jobs(limit: int = 30) -> list[Job]:
    folder = settings.data_dir / "jobs"
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    jobs: list[Job] = []
    for path in files[:limit]:
        job = get_job(path.stem)
        if job:
            jobs.append(job)
    return jobs