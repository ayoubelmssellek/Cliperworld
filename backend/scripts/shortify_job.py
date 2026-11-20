"""Reformat an existing job's clips into 9:16 vertical Shorts, then re-caption."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.jobs import get_job, save_job
from app.pipeline.captions import caption_clip, last_caption_error
from app.pipeline.shorts import make_vertical_short

job_id = sys.argv[1] if len(sys.argv) > 1 else "b839f0c40a5b"
clips_dir = Path(__file__).resolve().parents[2] / "data" / "clips" / job_id
job = get_job(job_id)
print("job", job_id, "found", bool(job), "clips", len(job.clips) if job else 0)

if not job:
    raise SystemExit(1)

for clip in job.clips:
    # Prefer raw landscape cut if short_* already replaced video_path
    candidates = [
        clips_dir / f"{clip.id}.mp4",
        Path(clip.video_path) if clip.video_path else None,
    ]
    src = next((p for p in candidates if p and p.exists() and not p.name.startswith("short_")), None)
    if not src:
        src = next((p for p in candidates if p and p.exists()), None)
    if not src:
        print("missing", clip.id)
        continue

    print("shortify", clip.id, "from", src.name)
    short = make_vertical_short(src, clips_dir / f"short_{clip.id}.mp4")
    clip.video_path = str(short)
    clip.status = "short"
    save_job(job)

    captioned = caption_clip(short, clips_dir)
    print("  caption", captioned, last_caption_error())
    if captioned:
        clip.captioned_path = str(captioned)
        clip.status = "captioned"
    save_job(job)

job.message = f"Done — {len(job.clips)} Short(s) ready (9:16)"
job.meta["activity"] = "Vertical Shorts ready to download"
job.meta["format"] = "9:16"
job.meta.pop("caption_error", None)
save_job(job)
print("saved")
