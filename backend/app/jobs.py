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
from app.pipeline.detect import detect_platform

_lock = threading.RLock()


def _job_path(job_id: str) -> Path:
    return settings.data_dir / "jobs" / f"{job_id}.json"


def create_job(url: str, *, max_clips: int, with_captions: bool) -> Job:
    platform = detect_platform(url)
    if platform is None:
        raise ValueError("URL must be a Twitch VOD or YouTube link")
    now = time.time()
    job = Job(
        id=uuid.uuid4().hex[:12],
        url=url,
        platform=platform,
        status=JobStatus.queued,
        message="Queued",
        with_captions=with_captions,
        max_clips=max_clips,
        created_at=now,
        updated_at=now,
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