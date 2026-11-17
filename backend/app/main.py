from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.jobs import create_job, get_job, list_jobs
from app.models import CreateJobRequest, HealthResponse, JobResponse
from app.paths import vendor_status
from app.pipeline.twitch import twitch_downloader_available
from app.pipeline.youtube import yt_dlp_available
from app.pipeline.cutter import ffmpeg_available
from app.runner import run_job

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve finished clips
clips_root = settings.data_dir / "clips"
clips_root.mkdir(parents=True, exist_ok=True)
app.mount("/media/clips", StaticFiles(directory=str(clips_root)), name="clips")


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    tools = {
        "ffmpeg": ffmpeg_available(),
        "twitch_downloader": twitch_downloader_available(),
        "yt_dlp": yt_dlp_available(),
        "auto_editor": shutil.which(settings.auto_editor_bin) is not None
        or (settings.auto_editor_dir / "auto_editor").exists(),
        "whisperx": False,
        "openshorts": bool(settings.openshorts_dir and settings.openshorts_dir.exists()),
    }
    tools.update({f"vendor_{k}": v for k, v in vendor_status().items()})
    try:
        import whisperx  # noqa: F401

        tools["whisperx"] = True
    except Exception:
        tools["whisperx"] = (vendor_status().get("whisperX") is True)
    return HealthResponse(ok=True, app=settings.app_name, tools=tools)


@app.post("/api/jobs", response_model=JobResponse)
def start_job(payload: CreateJobRequest, background: BackgroundTasks) -> JobResponse:
    max_clips = payload.max_clips or settings.max_clips
    try:
        job = create_job(payload.url, max_clips=max_clips, with_captions=payload.with_captions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background.add_task(run_job, job.id)
    return JobResponse(job=job)


@app.get("/api/jobs", response_model=list[JobResponse])
def jobs() -> list[JobResponse]:
    return [JobResponse(job=j) for j in list_jobs()]


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def job_detail(job_id: str) -> JobResponse:
    job = get_job(job_id)
    if not job:
        # Avoid 500s during brief write windows; client will poll again
        raise HTTPException(status_code=404, detail="Job not found or busy")
    return JobResponse(job=job)


@app.get("/api/jobs/{job_id}/clips/{clip_id}/download")
def download_clip(job_id: str, clip_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    clip = next((c for c in job.clips if c.id == clip_id), None)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    path = Path(clip.captioned_path or clip.video_path or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Clip file missing")
    return FileResponse(path, filename=path.name, media_type="video/mp4")