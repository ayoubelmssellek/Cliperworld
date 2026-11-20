from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.cancel import request_cancel
from app.config import settings
from app.jobs import create_job, get_job, list_jobs, save_job
from app.models import (
    CaptionStyleRequest,
    CreateJobRequest,
    HealthResponse,
    JobResponse,
    JobStatus,
    ReframeClipRequest,
)
from app.paths import vendor_status
from app.pipeline.streamcut_facecam import streamcut_available
from app.pipeline.twitch import download_busy, force_stop_download, twitch_downloader_available
from app.pipeline.youtube import yt_dlp_available
from app.pipeline.cutter import ffmpeg_available
from app.pipeline.clips_studio import clips_studio_available
from app.pipeline.kitty_brain import gemma_available, ollama_reachable, pick_gemma_model
from app.pipeline.shorts import openshorts_reframe_available, vertify_available
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
        "openshorts_reframe": openshorts_reframe_available(),
        "clips_studio": clips_studio_available(),
        "streamcut_facecam": streamcut_available(),
        "vertify": vertify_available(),
        "ollama": ollama_reachable(),
        "gemma": gemma_available(),
    }
    # Expose which Gemma tag would be used (helps setup)
    if tools["ollama"]:
        tools["gemma_model"] = bool(pick_gemma_model())
    tools.update({f"vendor_{k}": v for k, v in vendor_status().items()})
    try:
        import faster_whisper  # noqa: F401

        tools["faster_whisper"] = True
        tools["whisperx"] = True  # caption pipeline ready
    except Exception:
        tools["faster_whisper"] = False
        tools["whisperx"] = False
    return HealthResponse(ok=True, app=settings.app_name, tools=tools)


@app.post("/api/jobs", response_model=JobResponse)
def start_job(payload: CreateJobRequest, background: BackgroundTasks) -> JobResponse:
    max_clips = payload.max_clips or settings.max_clips
    try:
        job = create_job(
            payload.url,
            max_clips=max_clips,
            with_captions=payload.with_captions,
            with_gemma=payload.with_gemma,
            quality=payload.quality,
            layout=payload.layout,
            cam_zoom=payload.cam_zoom,
            game_zoom=payload.game_zoom,
            game_pan=payload.game_pan,
        )
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


@app.post("/api/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: str) -> JobResponse:
    """Stop a running job and free the Twitch download gate so another VOD can start."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {JobStatus.done, JobStatus.failed, JobStatus.cancelled}:
        force_stop_download()
        return JobResponse(job=job)

    request_cancel(job_id)
    force_stop_download()
    job.status = JobStatus.cancelled
    job.message = "Stopping…"
    job.error = None
    job.meta["stage"] = "cancelled"
    job.meta["activity"] = "Stop requested — killing download"
    save_job(job)
    return JobResponse(job=job)


@app.post("/api/downloads/stop")
def stop_download() -> dict:
    """Force-kill any Twitch download and clear the busy gate (works after a page refresh)."""
    was_busy = download_busy()
    force_stop_download()
    # Mark any still-active jobs as cancelled so UI recovers
    for job in list_jobs(limit=10):
        if job.status not in {JobStatus.done, JobStatus.failed, JobStatus.cancelled}:
            request_cancel(job.id)
            job.status = JobStatus.cancelled
            job.message = "Stopped"
            job.error = None
            job.meta["stage"] = "cancelled"
            job.meta["activity"] = "Stopped by user — you can start another download"
            save_job(job)
    return {"ok": True, "was_busy": was_busy}


@app.post("/api/jobs/{job_id}/clips/{clip_id}/reframe", response_model=JobResponse)
def reframe_clip(job_id: str, clip_id: str, payload: ReframeClipRequest) -> JobResponse:
    """Re-crop the phone game/cam view for one clip using zoom + pan (no re-download)."""
    from app.pipeline.layouts import hook_text_for_clip
    from app.pipeline.shorts import make_vertical_short

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    clip = next((c for c in job.clips if c.id == clip_id), None)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    clips_dir = settings.data_dir / "clips" / job_id
    landscape = clips_dir / f"{clip_id}.mp4"
    if not landscape.exists():
        raise HTTPException(
            status_code=404,
            detail="Landscape cut missing — generate clips again to enable phone reframe",
        )

    layout_id = (payload.layout or job.layout or "cam_hook_game").strip().lower()
    if layout_id not in {"cam_hook_game", "game_hook_cam"}:
        layout_id = "cam_hook_game"

    streamer = None
    if isinstance(job.meta.get("vod"), dict):
        streamer = job.meta["vod"].get("streamer")
    hook = hook_text_for_clip(
        title=clip.title,
        hook=clip.hook,
        samples=clip.sample_messages,
        streamer=streamer if isinstance(streamer, str) else None,
    )

    out = clips_dir / f"short_{landscape.name}"
    try:
        short = make_vertical_short(
            landscape,
            out,
            layout=layout_id,
            hook_text=hook,
            cam_zoom=payload.cam_zoom,
            game_zoom=payload.game_zoom,
            game_pan=payload.game_pan,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reframe failed: {exc}") from exc

    clip.video_path = str(short)
    clip.captioned_path = None  # old burn no longer matches the new crop
    clip.status = "short"

    job.cam_zoom = payload.cam_zoom
    job.game_zoom = payload.game_zoom
    job.game_pan = payload.game_pan
    job.meta["cam_zoom"] = payload.cam_zoom
    job.meta["game_zoom"] = payload.game_zoom
    job.meta["game_pan"] = payload.game_pan
    job.meta["layout"] = layout_id
    job.message = f"Reframed clip {clip_id[:6]} · zoom {payload.game_zoom:.2f}× pan {payload.game_pan:.2f}"
    save_job(job)
    return JobResponse(job=job)


@app.post("/api/jobs/{job_id}/clips/{clip_id}/captions", response_model=JobResponse)
def restyle_captions(
    job_id: str, clip_id: str, payload: CaptionStyleRequest
) -> JobResponse:
    """Re-burn karaoke captions with new position / font / colors (cached words)."""
    from app.pipeline.captions import last_caption_error, recaption_clip

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    clip = next((c for c in job.clips if c.id == clip_id), None)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    source = Path(clip.video_path or "")
    if not source.exists():
        raise HTTPException(status_code=404, detail="Short video missing for captions")

    style = payload.model_dump()
    job.meta["caption_style"] = style
    clips_dir = settings.data_dir / "clips" / job_id
    captioned = recaption_clip(source, clips_dir, style)
    if not captioned:
        raise HTTPException(
            status_code=500,
            detail=last_caption_error() or "Caption restyle failed",
        )

    clip.captioned_path = str(captioned)
    clip.status = "captioned"
    job.message = f"Captions updated · {style.get('font_name')} · {style.get('alignment')}"
    save_job(job)
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