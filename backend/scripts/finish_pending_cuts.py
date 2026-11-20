"""Finish a job stuck in Cut: encode pending clips, then Shorts + captions."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.jobs import get_job, save_job
from app.models import JobStatus
from app.pipeline.captions import caption_clip
from app.pipeline.cutter import cut_clip
from app.pipeline.shorts import make_vertical_short

JOB_ID = sys.argv[1] if len(sys.argv) > 1 else ""


def main() -> None:
    if not JOB_ID:
        raise SystemExit("usage: python scripts/finish_pending_cuts.py <job_id>")

    job = get_job(JOB_ID)
    if not job:
        raise SystemExit(f"job not found: {JOB_ID}")

    video = Path(job.video_path or "")
    if not video.exists():
        raise SystemExit(f"missing source video: {video}")

    clips_dir = settings.data_dir / "clips" / job.id
    clips_dir.mkdir(parents=True, exist_ok=True)
    total = max(1, len(job.clips))

    job.status = JobStatus.cutting
    job.message = "Finishing stuck cuts (fast path)"
    save_job(job)

    for index, clip in enumerate(job.clips, start=1):
        if clip.status not in {"pending", "queued"} and clip.video_path:
            continue
        print(f"cut {index}/{total} {clip.id} {clip.start}-{clip.end}", flush=True)
        job.meta["activity"] = f"Clip {index}/{total} · encoding {clip.end - clip.start:.0f}s"
        job.meta["progress"] = 70 + int(16 * (index - 1) / total)
        job.meta["clip_progress"] = {
            "index": index,
            "total": total,
            "done": index - 1,
            "phase": "encode",
            "label": f"{index - 1}/{total} cut · encoding #{index}",
        }
        save_job(job)
        out = clips_dir / f"{clip.id}.mp4"
        # Skip scene snap — that full-VOD scan is what hung clip 11
        cut_clip(video, clip.start, clip.end, out)
        clip.video_path = str(out)
        clip.status = "cut"
        job.meta["clip_progress"]["done"] = index
        job.meta["clip_progress"]["label"] = f"{index}/{total} cut"
        job.meta["progress"] = 70 + int(16 * index / total)
        job.meta["activity"] = f"Clip {index}/{total} · cut saved"
        save_job(job)

    if settings.short_format:
        job.status = JobStatus.cutting
        job.message = "Packaging vertical Shorts"
        job.meta["stage"] = "shorts"
        save_job(job)
        for index, clip in enumerate(job.clips, start=1):
            if not clip.video_path:
                continue
            if clip.status in {"short", "captioned"} and "short_" in Path(clip.video_path).name:
                continue
            print(f"short {index}/{total} {clip.id}", flush=True)
            job.meta["activity"] = f"Vertical short {index}/{total}"
            job.meta["progress"] = 86 + int(6 * index / total)
            job.meta["clip_progress"] = {
                "index": index,
                "total": total,
                "done": index - 1,
                "phase": "shorts",
                "label": f"9:16 · {index}/{total}",
            }
            save_job(job)
            src = Path(clip.video_path)
            short = make_vertical_short(src, clips_dir / f"short_{src.name}")
            clip.video_path = str(short)
            clip.status = "short"
            save_job(job)

    if job.with_captions:
        job.status = JobStatus.captioning
        job.message = "Adding captions"
        job.meta["stage"] = "captioning"
        save_job(job)
        for index, clip in enumerate(job.clips, start=1):
            if not clip.video_path or clip.captioned_path:
                continue
            print(f"caption {index}/{total} {clip.id}", flush=True)
            job.meta["activity"] = f"Captioning clip {index}/{total}"
            job.meta["progress"] = 92 + int(6 * ((index - 1) / total))
            job.meta["clip_progress"] = {
                "index": index,
                "total": total,
                "done": index - 1,
                "phase": "captions",
                "label": f"Caps · {index}/{total}",
            }
            save_job(job)
            captioned = caption_clip(Path(clip.video_path), clips_dir)
            if captioned:
                clip.captioned_path = str(captioned)
                clip.status = "captioned"
            else:
                clip.status = "ready"
            save_job(job)

    job.status = JobStatus.done
    job.message = f"Done — {len(job.clips)} Short(s) ready (9:16)"
    job.meta["stage"] = "done"
    job.meta["progress"] = 100
    job.meta["activity"] = "Vertical Shorts ready to download"
    job.meta["format"] = "9:16"
    job.meta["clip_progress"] = {
        "index": total,
        "total": total,
        "done": total,
        "phase": "done",
        "label": f"{total}/{total} ready",
    }
    save_job(job)
    print("DONE", job.id, flush=True)


if __name__ == "__main__":
    main()
