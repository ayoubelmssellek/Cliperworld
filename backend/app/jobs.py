from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from app.config import settings
from app.models import Job, JobStatus, Platform


def _job_path(job_id: str) -> Path:
    return settings.data_dir / "jobs" / f"{job_id}.json"


def create_job(url: str, *, max_clips: int, with_captions: bool) -> Job:
    now = time.time()
    job = Job(
        id=uuid.uuid4().hex[:12],
        url=url,
        platform=Platform.twitch,
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
    job.updated_at = time.time()
    path = _job_path(job.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(job.model_dump_json(indent=2), encoding="utf-8")


def get_job(job_id: str) -> Job | None:
    path = _job_path(job_id)
    if not path.exists():
        return None
    return Job.model_validate_json(path.read_text(encoding="utf-8"))


def list_jobs(limit: int = 30) -> list[Job]:
    folder = settings.data_dir / "jobs"
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    jobs: list[Job] = []
    for path in files[:limit]:
        try:
            jobs.append(Job.model_validate_json(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ValueError):
            continue
    return jobs