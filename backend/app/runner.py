from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any

from app.config import settings
from app.jobs import get_job, save_job
from app.models import JobStatus, Platform
from app.pipeline.audio_spikes import detect_audio_spikes
from app.pipeline.captions import caption_clip
from app.pipeline.chat_spikes import detect_chat_spikes
from app.pipeline.cutter import (
    cut_clip,
    maybe_silence_trim,
    probe_duration,
    spikes_to_candidates,
)
from app.pipeline.detect import detect_platform, parse_youtube_id
from app.pipeline.scenedetect import snap_to_scenes
from app.pipeline.twitch import download_vod_and_chat, fetch_vod_info, parse_twitch_vod_id
from app.pipeline.youtube import download_youtube_video_and_chat, fetch_youtube_info


def run_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    try:
        platform = job.platform or detect_platform(job.url)
        if platform is None:
            raise RuntimeError("Unsupported URL. Use a Twitch VOD or YouTube link.")

        job.platform = platform
        job.status = JobStatus.queued
        job.message = "Fetching cover + info"
        job.meta["stage"] = "info"
        job.meta["progress"] = 5
        save_job(job)

        download_dir = settings.data_dir / "downloads" / job.id
        last_progress_save = 0.0

        def on_progress(phase: str, extra: dict[str, Any]) -> None:
            nonlocal last_progress_save
            now = time.time()
            if phase in {"video_download_progress", "video_download_log"} and now - last_progress_save < 1.0:
                return
            current = get_job(job_id)
            if not current:
                return
            prev = current.meta.get("download") if isinstance(current.meta.get("download"), dict) else {}
            current.meta["download"] = {**prev, "phase": phase, **extra}
            quality = (
                settings.twitch_download_quality
                if current.platform == Platform.twitch
                else settings.youtube_format
            )
            if phase == "video_download_progress":
                current.meta["activity"] = f"Downloading video… {extra.get('bytes_label', '')}".strip()
                current.message = (
                    f"Downloading video ({quality}) — {extra.get('bytes_label', 'starting')}"
                )
                current.meta["progress"] = min(55, 12 + int((extra.get("bytes") or 0) / (80 * 1024 * 1024)))
            elif phase == "video_download_log":
                current.meta["activity"] = extra.get("line") or current.meta.get("activity")
            elif phase == "chat_download_start":
                current.meta["stage"] = "downloading_chat"
                current.meta["progress"] = 58
                current.message = "Downloading chat / live chat"
                current.meta["activity"] = "Pulling chat for spike detection"
            save_job(current)
            last_progress_save = now

        if platform == Platform.twitch:
            vod_id = parse_twitch_vod_id(job.url)
            if not vod_id:
                raise RuntimeError("Not a Twitch VOD URL. Example: https://www.twitch.tv/videos/123456789")
            job.vod_id = vod_id
            info = fetch_vod_info(vod_id)
            job.meta["vod"] = info
            job.meta["activity"] = f"Found {info.get('streamer')} — {info.get('title')}"
            job.status = JobStatus.downloading
            job.message = (
                f"Downloading {info.get('length_label', 'VOD')} at "
                f"{settings.twitch_download_quality} via TwitchDownloader"
            )
            job.meta["stage"] = "downloading_video"
            job.meta["progress"] = 12
            save_job(job)

            video_path, chat_path = download_vod_and_chat(
                vod_id,
                download_dir,
                on_progress=on_progress,
            )
        else:
            yt_id = parse_youtube_id(job.url) or "youtube"
            job.vod_id = yt_id
            info = fetch_youtube_info(job.url)
            job.vod_id = info.get("vod_id") or yt_id
            job.meta["vod"] = info
            job.meta["activity"] = f"Found {info.get('streamer')} — {info.get('title')}"
            job.status = JobStatus.downloading
            job.message = (
                f"Downloading {info.get('length_label', 'video')} via yt-dlp"
            )
            job.meta["stage"] = "downloading_video"
            job.meta["progress"] = 12
            save_job(job)

            video_path, chat_path = download_youtube_video_and_chat(
                job.url,
                download_dir,
                on_progress=on_progress,
            )

        job = get_job(job_id) or job
        job.video_path = str(video_path)
        job.chat_path = str(chat_path) if chat_path else None
        job.meta["progress"] = 62
        job.meta["activity"] = "Download complete"
        save_job(job)

        job.status = JobStatus.analyzing_chat
        job.meta["stage"] = "analyzing_chat"
        job.meta["progress"] = 70

        spikes = []
        if chat_path and Path(chat_path).exists():
            job.message = "Scanning chat for blow-up moments"
            job.meta["activity"] = "Measuring chat velocity spikes"
            save_job(job)
            spikes = detect_chat_spikes(Path(chat_path), max_spikes=job.max_clips)

        if not spikes:
            job.message = "No chat spikes — scanning audio loudness"
            job.meta["activity"] = "Fallback: audio spike detection"
            save_job(job)
            spikes = detect_audio_spikes(video_path, max_spikes=job.max_clips)

        job.spikes = spikes
        duration = probe_duration(video_path)
        candidates = spikes_to_candidates(spikes, duration=duration)
        job.clips = candidates
        job.meta["spike_count"] = len(spikes)
        if not candidates:
            job.status = JobStatus.done
            job.message = "No strong moments found. Try another video or lower thresholds."
            job.meta["stage"] = "done"
            job.meta["progress"] = 100
            save_job(job)
            return
        save_job(job)

        job.status = JobStatus.cutting
        job.message = f"Cutting {len(candidates)} clips with FFmpeg"
        job.meta["stage"] = "cutting"
        job.meta["progress"] = 75
        save_job(job)

        clips_dir = settings.data_dir / "clips" / job.id
        clips_dir.mkdir(parents=True, exist_ok=True)

        for index, clip in enumerate(job.clips, start=1):
            job.meta["activity"] = f"Cutting clip {index}/{len(job.clips)}"
            job.meta["progress"] = 75 + int(15 * (index / max(1, len(job.clips))))
            save_job(job)
            start, end = snap_to_scenes(video_path, clip.start, clip.end)
            clip.start, clip.end = round(start, 2), round(end, 2)
            out = clips_dir / f"{clip.id}.mp4"
            cut_clip(video_path, clip.start, clip.end, out)
            trimmed = maybe_silence_trim(out)
            clip.video_path = str(trimmed)
            clip.status = "cut"
            save_job(job)

        if job.with_captions:
            job.status = JobStatus.captioning
            job.message = "Adding captions (OpenShorts / WhisperX)"
            job.meta["stage"] = "captioning"
            job.meta["progress"] = 92
            save_job(job)
            for index, clip in enumerate(job.clips, start=1):
                if not clip.video_path:
                    continue
                job.meta["activity"] = f"Captioning clip {index}/{len(job.clips)}"
                save_job(job)
                captioned = caption_clip(Path(clip.video_path), clips_dir)
                if captioned:
                    clip.captioned_path = str(captioned)
                    clip.status = "captioned"
                else:
                    clip.status = "ready"
                save_job(job)
        else:
            for clip in job.clips:
                clip.status = "ready"

        job.status = JobStatus.done
        job.message = f"Done — {len(job.clips)} clip(s) ready"
        job.meta["stage"] = "done"
        job.meta["progress"] = 100
        job.meta["activity"] = "Clips ready to download"
        save_job(job)
    except Exception as exc:
        job = get_job(job_id) or job
        job.status = JobStatus.failed
        job.error = str(exc)
        job.message = "Failed"
        job.meta["stage"] = "failed"
        job.meta["activity"] = str(exc)[:240]
        job.meta["traceback"] = traceback.format_exc()[-4000:]
        save_job(job)