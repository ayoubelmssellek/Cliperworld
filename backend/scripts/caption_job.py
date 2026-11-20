from pathlib import Path

from app.jobs import get_job, save_job
from app.pipeline.captions import caption_clip, last_caption_error

job_id = "b839f0c40a5b"
d = Path(__file__).resolve().parents[2] / "data" / "clips" / job_id
job = get_job(job_id)
print("job", bool(job), "clips", len(job.clips) if job else 0)
for clip in job.clips if job else []:
    src = Path(clip.video_path) if clip.video_path else None
    if not src or not src.exists():
        print("missing", clip.id)
        continue
    out = caption_clip(src, d)
    print(clip.id, "->", out, last_caption_error())
    if out:
        clip.captioned_path = str(out)
        clip.status = "captioned"
if job:
    job.message = f"Done — {len(job.clips)} clip(s) ready (captioned)"
    job.meta["activity"] = "Clips ready with captions"
    job.meta.pop("caption_error", None)
    save_job(job)
    print("saved")
