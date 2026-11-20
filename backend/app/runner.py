from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any

from app.cancel import check as check_cancel, clear_cancel, is_cancelled
from app.config import settings
from app.jobs import get_job, save_job
from app.models import JobStatus, Platform
from app.pipeline.audio_spikes import detect_audio_spikes
from app.pipeline.captions import caption_clip, last_caption_error
from app.pipeline.chat_spikes import detect_chat_spikes
from app.pipeline.cutter import (
    cut_clip,
    maybe_silence_trim,
    probe_duration,
    spikes_to_candidates,
)
from app.pipeline.layouts import hook_text_for_clip
from app.pipeline.shorts import make_vertical_short
from app.pipeline.detect import detect_platform, parse_youtube_id
from app.pipeline.scenedetect import snap_to_scenes
from app.pipeline.quality import (
    quality_label,
    twitch_quality,
    youtube_fallback_format,
    youtube_format,
)
from app.pipeline.twitch import (
    download_vod_and_chat,
    fetch_vod_info,
    force_stop_download,
    parse_twitch_vod_id,
)
from app.pipeline.youtube import download_youtube_video_and_chat, fetch_youtube_info
from app.pipeline.clips_studio import chat_hype_events
from app.pipeline.chat_spikes import load_chat_with_authors
from app.pipeline.kitty_brain import (
    enrich_clips_with_gemma,
    friendly_gemma_error,
    gemma_available,
    kitty_picks_to_candidates,
    pick_gemma_model,
    score_with_gemma,
    transcribe_segments,
)


def run_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return

    clear_cancel(job_id)
    try:
        platform = job.platform or detect_platform(job.url)
        if platform is None:
            raise RuntimeError("Unsupported URL. Use a Twitch VOD or YouTube link.")

        job.platform = platform
        q_label = quality_label(job.quality)
        job.status = JobStatus.queued
        job.message = "Fetching cover + info"
        job.meta["stage"] = "info"
        job.meta["progress"] = 5
        job.meta["quality_label"] = q_label
        save_job(job)
        check_cancel(job_id)

        download_dir = settings.data_dir / "downloads" / job.id
        last_progress_save = 0.0

        def on_progress(phase: str, extra: dict[str, Any]) -> None:
            nonlocal last_progress_save
            if is_cancelled(job_id):
                force_stop_download()
                return
            now = time.time()
            if (
                phase
                in {
                    "video_download_progress",
                    "video_download_log",
                    "chat_download_progress",
                    "chat_download_log",
                }
                and now - last_progress_save < 1.0
            ):
                return
            current = get_job(job_id)
            if not current:
                return
            prev = current.meta.get("download") if isinstance(current.meta.get("download"), dict) else {}
            current.meta["download"] = {**prev, "phase": phase, **extra}
            if phase == "video_download_progress":
                percent = extra.get("percent")
                bytes_label = extra.get("bytes_label")
                line = extra.get("line")
                if isinstance(percent, int):
                    current.meta["activity"] = line or f"Downloading… {percent}%"
                    current.message = f"Downloading video ({q_label}) — {percent}%"
                    current.meta["progress"] = min(55, 12 + int(percent * 0.43))
                else:
                    current.meta["activity"] = (
                        f"Downloading video… {bytes_label or line or ''}".strip()
                    )
                    current.message = (
                        f"Downloading video ({q_label}) — {bytes_label or 'starting parts…'}"
                    )
                    if bytes_label and bytes_label != "0 B":
                        current.meta["progress"] = min(
                            55, 12 + int((extra.get("bytes") or 0) / (40 * 1024 * 1024))
                        )
            elif phase == "video_download_log":
                current.meta["activity"] = extra.get("line") or current.meta.get("activity")
                line = str(extra.get("line") or "")
                if "%" in line:
                    current.message = f"Downloading video ({q_label}) — {line[-80:]}"
            elif phase == "video_download_skip":
                current.meta["stage"] = "downloading_video"
                current.meta["progress"] = 55
                current.message = f"Using cached video ({extra.get('bytes_label') or 'ready'})"
                current.meta["activity"] = "Skipped re-download — video already on disk"
            elif phase == "chat_download_start":
                current.meta["stage"] = "downloading_chat"
                current.meta["progress"] = 58
                current.message = "Downloading chat / live chat"
                current.meta["activity"] = "Pulling chat for spike detection"
            elif phase == "chat_download_progress":
                current.meta["stage"] = "downloading_chat"
                percent = extra.get("percent")
                line = extra.get("line")
                if isinstance(percent, int):
                    current.meta["progress"] = min(70, 58 + int(percent * 0.12))
                    current.message = f"Downloading chat / live chat — {percent}%"
                    current.meta["activity"] = line or f"Chat download {percent}%"
                else:
                    current.meta["activity"] = line or current.meta.get("activity")
                    current.message = "Downloading chat / live chat…"
            elif phase == "chat_download_log":
                current.meta["stage"] = "downloading_chat"
                line = str(extra.get("line") or "")
                current.meta["activity"] = line or current.meta.get("activity")
                if "%" in line:
                    current.message = f"Downloading chat / live chat — {line[-80:]}"
            elif phase == "chat_download_failed":
                current.meta["stage"] = "downloading_chat"
                current.meta["progress"] = 62
                current.message = "Chat download skipped — using audio spikes"
                current.meta["activity"] = str(extra.get("error") or "chat unavailable")[:200]
                current.meta["chat_download_error"] = extra.get("error")
            elif phase == "chat_download_done":
                current.meta["stage"] = "downloading_chat"
                current.meta["progress"] = 62
                current.message = "Chat ready"
                current.meta["activity"] = "Chat downloaded for spike detection"
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
                f"Downloading {info.get('length_label', 'VOD')} at {q_label} via TwitchDownloader"
            )
            job.meta["stage"] = "downloading_video"
            job.meta["progress"] = 12
            save_job(job)

            video_path, chat_path = download_vod_and_chat(
                vod_id,
                download_dir,
                quality=twitch_quality(job.quality),
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
            job.message = f"Downloading {info.get('length_label', 'video')} at {q_label} via yt-dlp"
            job.meta["stage"] = "downloading_video"
            job.meta["progress"] = 12
            save_job(job)

            video_path, chat_path = download_youtube_video_and_chat(
                job.url,
                download_dir,
                format_selector=youtube_format(job.quality),
                fallback_format=youtube_fallback_format(job.quality),
                on_progress=on_progress,
            )

        check_cancel(job_id)
        job = get_job(job_id) or job
        job.video_path = str(video_path)
        job.chat_path = str(chat_path) if chat_path else None
        job.meta["progress"] = 62
        job.meta["activity"] = "Download complete"
        save_job(job)

        check_cancel(job_id)
        job.status = JobStatus.analyzing_chat
        job.meta["stage"] = "analyzing_chat"
        job.meta["progress"] = 70

        spikes = []
        if chat_path and Path(chat_path).exists():
            job.message = "Scanning chat for blow-up moments"
            job.meta["activity"] = "Measuring chat velocity spikes (+ Clips Kitty hype)"
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
        job.meta["spike_count"] = len(spikes)

        # Clips Kitty brain: chat finds windows → Gemma scores + titles them
        if settings.kitty_llm_enabled and job.with_gemma and gemma_available():
            model = pick_gemma_model() or settings.kitty_llm_model
            job.message = f"Gemma scoring chat moments ({model})"
            job.meta["stage"] = "gemma"
            job.meta["activity"] = f"Clips Kitty score_windows · {model}"
            job.meta["progress"] = 72
            job.meta["kitty_model"] = model
            save_job(job)
            try:
                work = settings.data_dir / "tmp" / job.id / "kitty"
                events: list[tuple[float, str]] = []
                if chat_path and Path(chat_path).exists():
                    full = load_chat_with_authors(Path(chat_path))
                    if full:
                        for ev in chat_hype_events(full, float(duration or full[-1][0] + 10)):
                            events.append((float(ev["second"]), str(ev["label"])))
                vod_title = ""
                if isinstance(job.meta.get("vod"), dict):
                    vod_title = str(job.meta["vod"].get("title") or "")

                if candidates:
                    # Real Kitty path: score the chat windows (small prompts, works on gemma3:4b)
                    before = len(candidates)
                    candidates = enrich_clips_with_gemma(
                        candidates[: job.max_clips],
                        video_path,
                        events=events,
                        video_title=vod_title,
                        work_dir=work,
                    )
                    job.meta["gemma_picks"] = sum(1 for c in candidates if c.source == "gemma+chat")
                    job.meta["picker"] = "gemma+chat" if job.meta["gemma_picks"] else "chat"
                    job.meta["activity"] = (
                        f"Gemma scored {job.meta['gemma_picks']}/{before} chat moments"
                    )
                else:
                    # No chat spikes — discovery over transcript (heavier)
                    segments = transcribe_segments(video_path, work)
                    picks = score_with_gemma(
                        segments,
                        events=events,
                        max_clips=job.max_clips,
                        min_duration=max(10.0, settings.clip_pre_seconds),
                        max_duration=settings.clip_pre_seconds + settings.clip_post_seconds + 15,
                        video_title=vod_title,
                    )
                    gemma_clips = kitty_picks_to_candidates(picks)
                    job.meta["gemma_picks"] = len(gemma_clips)
                    if gemma_clips:
                        candidates = gemma_clips
                        job.meta["picker"] = "gemma"
                    else:
                        job.meta["picker"] = "chat"
            except Exception as exc:
                friendly = friendly_gemma_error(str(exc))
                job.meta["gemma_error"] = friendly
                job.meta["picker"] = "chat"
                job.meta["activity"] = f"Gemma skipped — chat spikes · {friendly}"[:240]
        else:
            job.meta["picker"] = "chat"
            if settings.kitty_llm_enabled and job.with_gemma:
                job.meta["gemma_hint"] = (
                    "Install Ollama + pull a Gemma model to unlock Clips Kitty AI scoring. "
                    "See docs/VENDOR-STACK.md"
                )
            elif not job.with_gemma:
                job.meta["gemma_hint"] = "Gemma AI picks turned off for this job"

        check_cancel(job_id)
        job.clips = candidates
        if not candidates:
            job.status = JobStatus.done
            job.message = "No strong moments found. Try another video or lower thresholds."
            job.meta["stage"] = "done"
            job.meta["progress"] = 100
            save_job(job)
            return
        save_job(job)

        check_cancel(job_id)
        job.status = JobStatus.cutting
        job.message = f"Cutting {len(candidates)} clips with FFmpeg"
        job.meta["stage"] = "cutting"
        job.meta["progress"] = 75
        save_job(job)

        clips_dir = settings.data_dir / "clips" / job.id
        clips_dir.mkdir(parents=True, exist_ok=True)

        total_clips = max(1, len(job.clips))
        for index, clip in enumerate(job.clips, start=1):
            check_cancel(job_id)
            done = index - 1
            job.message = f"Cutting clip {index} of {total_clips}"
            job.meta["clip_progress"] = {
                "index": index,
                "total": total_clips,
                "done": done,
                "phase": "scene",
                "label": f"{done}/{total_clips} cut · working #{index}",
            }
            # Cut owns 70→86 so the bar actually moves per clip
            job.meta["progress"] = 70 + int(16 * done / total_clips)
            job.meta["activity"] = f"Clip {index}/{total_clips} · scene snap"
            save_job(job)
            start, end = snap_to_scenes(video_path, clip.start, clip.end)
            clip.start, clip.end = round(start, 2), round(end, 2)
            out = clips_dir / f"{clip.id}.mp4"
            job.meta["clip_progress"]["phase"] = "encode"
            job.meta["clip_progress"]["label"] = (
                f"{done}/{total_clips} cut · encoding #{index} ({clip.end - clip.start:.0f}s)"
            )
            job.meta["activity"] = (
                f"Clip {index}/{total_clips} · encoding {clip.end - clip.start:.0f}s"
            )
            save_job(job)
            cut_clip(video_path, clip.start, clip.end, out)
            trimmed = maybe_silence_trim(out)
            clip.video_path = str(trimmed)
            clip.status = "cut"
            job.meta["clip_progress"]["done"] = index
            job.meta["clip_progress"]["phase"] = "done"
            job.meta["clip_progress"]["label"] = f"{index}/{total_clips} cut"
            job.meta["progress"] = 70 + int(16 * index / total_clips)
            job.meta["activity"] = f"Clip {index}/{total_clips} · cut saved"
            save_job(job)

        if settings.short_format:
            check_cancel(job_id)
            layout_id = (job.layout or job.meta.get("layout") or "blur").strip().lower()
            job.status = JobStatus.shorts
            job.message = f"Packaging vertical Shorts · layout {layout_id}"
            job.meta["stage"] = "shorts"
            job.meta["layout"] = layout_id
            job.meta["progress"] = 86
            save_job(job)
            streamer = None
            if isinstance(job.meta.get("vod"), dict):
                streamer = job.meta["vod"].get("streamer")
            for index, clip in enumerate(job.clips, start=1):
                check_cancel(job_id)
                if not clip.video_path:
                    continue
                done = index - 1
                job.message = f"Vertical short {index} of {total_clips} · {layout_id}"
                job.meta["clip_progress"] = {
                    "index": index,
                    "total": total_clips,
                    "done": done,
                    "phase": "shorts",
                    "label": f"9:16 · {layout_id} · {index}/{total_clips}",
                }
                job.meta["activity"] = f"Vertical short {index}/{total_clips} · {layout_id}"
                job.meta["progress"] = 86 + int(6 * (done / total_clips))
                save_job(job)
                src = Path(clip.video_path)
                hook = hook_text_for_clip(
                    title=clip.title,
                    hook=clip.hook,
                    samples=clip.sample_messages,
                    streamer=streamer if isinstance(streamer, str) else None,
                )
                short = make_vertical_short(
                    src,
                    clips_dir / f"short_{src.name}",
                    layout=layout_id,
                    hook_text=hook,
                    cam_zoom=float(job.cam_zoom or job.meta.get("cam_zoom") or 1.0),
                    game_zoom=float(job.game_zoom or job.meta.get("game_zoom") or 1.0),
                    game_pan=float(job.game_pan or job.meta.get("game_pan") or 0.55),
                )
                # Keep landscape cut on disk as {id}.mp4 for later phone reframe
                clip.video_path = str(short)
                clip.status = "short"
                job.meta["clip_progress"]["done"] = index
                job.meta["clip_progress"]["label"] = (
                    f"9:16 · {layout_id} · {index}/{total_clips} packaged"
                )
                job.meta["progress"] = 86 + int(6 * (index / total_clips))
                save_job(job)

        if job.with_captions:
            check_cancel(job_id)
            job.status = JobStatus.captioning
            job.message = "Adding captions (OpenShorts / WhisperX)"
            job.meta["stage"] = "captioning"
            job.meta["progress"] = 92
            save_job(job)
            caption_failures = 0
            for index, clip in enumerate(job.clips, start=1):
                check_cancel(job_id)
                if not clip.video_path:
                    continue
                job.message = f"Captioning clip {index} of {total_clips}"
                job.meta["clip_progress"] = {
                    "index": index,
                    "total": total_clips,
                    "done": index - 1,
                    "phase": "captions",
                    "label": f"Caps · {index}/{total_clips}",
                }
                job.meta["activity"] = f"Captioning clip {index}/{total_clips}"
                job.meta["progress"] = 92 + int(6 * ((index - 1) / total_clips))
                save_job(job)
                captioned = caption_clip(Path(clip.video_path), clips_dir)
                if captioned:
                    clip.captioned_path = str(captioned)
                    clip.status = "captioned"
                else:
                    clip.status = "ready"
                    caption_failures += 1
                    err = last_caption_error()
                    if err:
                        job.meta["caption_error"] = err
                save_job(job)
            if caption_failures and not any(c.captioned_path for c in job.clips):
                job.meta["activity"] = (
                    f"Clips ready (captions skipped: {job.meta.get('caption_error', 'unknown')})"
                )
        else:
            for clip in job.clips:
                clip.status = "ready"

        job.status = JobStatus.done
        job.message = f"Done — {len(job.clips)} Short(s) ready (9:16)"
        job.meta["stage"] = "done"
        job.meta["progress"] = 100
        job.meta["activity"] = "Vertical Shorts ready to download"
        job.meta["format"] = "9:16"
        save_job(job)
    except Exception as exc:
        job = get_job(job_id) or job
        stopped = is_cancelled(job_id) or "cancelled" in str(exc).lower() or "stopped" in str(exc).lower()
        if stopped:
            force_stop_download()
            job.status = JobStatus.cancelled
            job.error = None
            job.message = "Stopped"
            job.meta["stage"] = "cancelled"
            job.meta["activity"] = "Stopped by user — you can start another download"
        else:
            job.status = JobStatus.failed
            job.error = str(exc)
            job.message = "Failed"
            job.meta["stage"] = "failed"
            job.meta["activity"] = str(exc)[:240]
        if not stopped:
            job.meta["traceback"] = traceback.format_exc()[-4000:]
        save_job(job)
    finally:
        clear_cancel(job_id)