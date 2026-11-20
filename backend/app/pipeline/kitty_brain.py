"""
Clips Kitty brain glue — Gemma / Ollama scoring + titles.

How Clips Kitty actually uses Gemma on a weak PC:
  1. Chat (or other signals) propose time windows
  2. score_windows() asks Gemma to score/hook those windows only
  3. metadata batch writes titles / descriptions / hashtags

We do NOT dump the whole VOD into find_highlights() — that one mega-prompt
is what timed out gemma3:4b and made it look like Gemma “wasn’t used”.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import httpx

from app.config import settings
from app.models import ClipCandidate
from app.paths import CLIPS_STUDIO_DIR
from app.pipeline.captions import _extract_wav, _get_model, _load_wav_f32


def ollama_reachable(host: str | None = None) -> bool:
    base = (host or settings.kitty_ollama_host).rstrip("/")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def ollama_models(host: str | None = None) -> list[str]:
    base = (host or settings.kitty_ollama_host).rstrip("/")
    try:
        r = httpx.get(f"{base}/api/tags", timeout=3.0)
        r.raise_for_status()
        models = r.json().get("models") or []
        return [str(m.get("name") or "") for m in models if m.get("name")]
    except Exception:
        return []


def gemma_available() -> bool:
    if not CLIPS_STUDIO_DIR.exists():
        return False
    if not ollama_reachable():
        return False
    names = [n.lower() for n in ollama_models()]
    return any("gemma" in n for n in names)


def pick_gemma_model() -> str | None:
    names = ollama_models()
    preferred = [
        settings.kitty_llm_model,
        "gemma3:4b",
        "gemma4:e2b",
        "gemma:7b",
        "gemma3:12b",
        "gemma4:e4b",
    ]
    lower_map = {n.lower(): n for n in names}
    for want in preferred:
        key = want.lower()
        if key in lower_map:
            return lower_map[key]
        for name, orig in lower_map.items():
            if name.startswith(key) or key in name:
                return orig
    for name, orig in lower_map.items():
        if "gemma" in name:
            return orig
    return None


def transcribe_segments(video_path: Path, work_dir: Path) -> list[dict]:
    """Full-file transcript (slow). Prefer transcribe_windows for Gemma enrich."""
    work_dir.mkdir(parents=True, exist_ok=True)
    wav = work_dir / "source.wav"
    if not _extract_wav(video_path, wav):
        return []
    model = _get_model()
    audio = _load_wav_f32(wav)
    segs, _info = model.transcribe(audio, language=None, vad_filter=True)
    out: list[dict] = []
    for seg in segs:
        text = (seg.text or "").strip()
        if not text:
            continue
        out.append({"start": float(seg.start), "end": float(seg.end), "text": text})
    return out


def transcribe_windows(
    video_path: Path,
    windows: list[tuple[float, float]],
    work_dir: Path,
    *,
    pad: float = 3.0,
) -> list[dict]:
    """Whisper only the clip windows Gemma will score — fast on weak PCs."""
    work_dir.mkdir(parents=True, exist_ok=True)
    model = _get_model()
    out: list[dict] = []
    for index, (start, end) in enumerate(windows):
        pad_start = max(0.0, float(start) - pad)
        pad_end = float(end) + pad
        duration = max(0.5, pad_end - pad_start)
        wav = work_dir / f"window_{index}.wav"
        if not _extract_wav_range(video_path, wav, pad_start, duration):
            continue
        try:
            audio = _load_wav_f32(wav)
            segs, _info = model.transcribe(audio, language=None, vad_filter=True)
        except Exception:
            continue
        for seg in segs:
            text = (seg.text or "").strip()
            if not text:
                continue
            out.append(
                {
                    "start": round(pad_start + float(seg.start), 2),
                    "end": round(pad_start + float(seg.end), 2),
                    "text": text,
                }
            )
    out.sort(key=lambda s: s["start"])
    return out


def _extract_wav_range(video_path: Path, wav_path: Path, start: float, duration: float) -> bool:
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(wav_path),
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return wav_path.exists() and wav_path.stat().st_size > 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def enrich_clips_with_gemma(
    clips: list[ClipCandidate],
    video_path: Path,
    *,
    events: list[tuple[float, str]] | None = None,
    video_title: str = "",
    work_dir: Path,
) -> list[ClipCandidate]:
    """
    Clips Kitty path: score + title the chat windows with Gemma.
    Never drops chat picks — on failure returns the originals unchanged.
    """
    model = pick_gemma_model()
    if not model or not clips:
        return clips

    windows = [(float(c.start), float(c.end)) for c in clips]
    segments = transcribe_windows(video_path, windows, work_dir)
    # Even with no speech, score_windows can still use chat events for hooks
    payload_segments = segments or [{"start": w[0], "end": w[1], "text": "(no speech)"} for w in windows]

    with tempfile.TemporaryDirectory(prefix="cw_kitty_enrich_") as tmp:
        tmp_path = Path(tmp)
        in_path = tmp_path / "in.json"
        out_path = tmp_path / "out.json"
        in_path.write_text(
            json.dumps(
                {
                    "segments": payload_segments,
                    "windows": [[s, e] for s, e in windows],
                    "events": [[t, str(label)] for t, label in (events or [])],
                    "video_title": video_title or "Untitled",
                    "model": model,
                    "host": settings.kitty_ollama_host,
                    # Small prompts → give each Ollama call enough room on weak CPUs
                    "ollama_timeout": min(420, max(120, int(settings.kitty_llm_timeout / 3))),
                    "batch": 4,
                }
            ),
            encoding="utf-8",
        )

        script = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, r"{CLIPS_STUDIO_DIR.as_posix()}")

from core.models import Segment, ClipCandidate
from llm.registry import create_backend
from analysis.highlights import score_windows
from analysis.metadata import generate_metadata_batch

payload = json.loads(Path(r"{in_path.as_posix()}").read_text(encoding="utf-8"))
segments = [Segment(start=s["start"], end=s["end"], text=s["text"]) for s in payload["segments"]]
windows = [(float(a), float(b)) for a, b in payload["windows"]]
events = [(float(t), str(label)) for t, label in payload.get("events") or []]
llm = create_backend({{
    "backend": f"ollama/{{payload['model']}}",
    "ollama_host": payload["host"],
    "temperature": 0.4,
    "num_ctx": 4096,
}})
if hasattr(llm, "timeout"):
    llm.timeout = int(payload.get("ollama_timeout") or 180)

scored = score_windows(
    segments,
    llm,
    windows,
    events=events or None,
    events_title="CHAT / AUDIENCE EVENTS",
    batch=int(payload.get("batch") or 4),
    warn=True,
)
meta = generate_metadata_batch(
    scored, segments, payload.get("video_title") or "Untitled", llm, batch_size=4
)
rows = []
for i, c in enumerate(scored):
    m = meta[i] if i < len(meta) else None
    rows.append({{
        "start": float(c.start),
        "end": float(c.end),
        "score": float(c.score),
        "hook": c.hook or "",
        "reason": c.reason or "",
        "title": getattr(m, "title", "") if m else "",
        "description": getattr(m, "description", "") if m else "",
        "hashtags": list(getattr(m, "hashtags", []) or []) if m else [],
    }})
Path(r"{out_path.as_posix()}").write_text(json.dumps(rows), encoding="utf-8")
print(len(rows))
"""
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(CLIPS_STUDIO_DIR),
                timeout=settings.kitty_llm_timeout,
            )
        except Exception as exc:
            raise RuntimeError(f"Gemma enrich failed to start: {exc}") from exc

        if proc.returncode != 0 or not out_path.exists():
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(friendly_gemma_error(detail))

        rows = json.loads(out_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows:
            return clips

        enriched: list[ClipCandidate] = []
        for index, clip in enumerate(clips):
            row = rows[index] if index < len(rows) else {}
            gemma_score = float(row.get("score") or 0)
            # Blend chat engagement with Gemma viral score when both exist
            blended = round((float(clip.score) * 0.35) + (gemma_score * 0.65), 2) if gemma_score else clip.score
            hook = str(row.get("hook") or "").strip() or clip.hook
            reason = str(row.get("reason") or "").strip() or clip.reason
            title = str(row.get("title") or "").strip() or clip.title
            description = str(row.get("description") or "").strip() or clip.description
            hashtags = list(row.get("hashtags") or clip.hashtags or [])
            samples = list(clip.sample_messages)
            if hook and hook not in samples:
                samples = [hook, *samples][:5]
            enriched.append(
                clip.model_copy(
                    update={
                        "score": blended,
                        "hook": hook,
                        "reason": reason,
                        "title": title,
                        "description": description,
                        "hashtags": hashtags,
                        "sample_messages": samples,
                        "source": "gemma+chat",
                    }
                )
            )
        return enriched


def score_with_gemma(
    segments: list[dict],
    *,
    events: list[tuple[float, str]] | None = None,
    max_clips: int = 8,
    min_duration: float = 12.0,
    max_duration: float = 45.0,
    video_title: str = "",
) -> list[dict]:
    """
    Discovery mode (no chat spikes): full find_highlights.
    Prefer enrich_clips_with_gemma when chat windows already exist.
    """
    model = pick_gemma_model()
    if not model or not segments:
        return []

    with tempfile.TemporaryDirectory(prefix="cw_kitty_brain_") as tmp:
        tmp_path = Path(tmp)
        in_path = tmp_path / "in.json"
        out_path = tmp_path / "out.json"
        in_path.write_text(
            json.dumps(
                {
                    "segments": segments,
                    "events": [[t, str(label)] for t, label in (events or [])],
                    "max_clips": max_clips,
                    "min_duration": min_duration,
                    "max_duration": max_duration,
                    "video_title": video_title or "Untitled",
                    "model": model,
                    "host": settings.kitty_ollama_host,
                    "ollama_timeout": min(420, max(120, int(settings.kitty_llm_timeout / 3))),
                }
            ),
            encoding="utf-8",
        )

        script = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, r"{CLIPS_STUDIO_DIR.as_posix()}")

from core.models import Segment
from llm.registry import create_backend
from analysis.highlights import find_highlights
from analysis.metadata import generate_metadata_batch

payload = json.loads(Path(r"{in_path.as_posix()}").read_text(encoding="utf-8"))
segments = [Segment(start=s["start"], end=s["end"], text=s["text"]) for s in payload["segments"]]
events = [(float(t), str(label)) for t, label in payload.get("events") or []]
llm = create_backend({{
    "backend": f"ollama/{{payload['model']}}",
    "ollama_host": payload["host"],
    "temperature": 0.4,
    "num_ctx": 4096,
}})
if hasattr(llm, "timeout"):
    llm.timeout = int(payload.get("ollama_timeout") or 180)
clips, _rej = find_highlights(
    segments,
    llm,
    min_score=55,
    max_clips=int(payload["max_clips"]),
    min_duration=float(payload["min_duration"]),
    max_duration=float(payload["max_duration"]),
    events=events or None,
    events_title="CHAT / AUDIENCE EVENTS",
    chunk_seconds=480.0,
)
meta = generate_metadata_batch(
    clips, segments, payload.get("video_title") or "Untitled", llm, batch_size=4
)
rows = []
for i, c in enumerate(clips):
    m = meta[i] if i < len(meta) else None
    rows.append({{
        "start": float(c.start),
        "end": float(c.end),
        "score": float(c.score),
        "hook": c.hook or "",
        "reason": c.reason or "",
        "trending": bool(getattr(c, "trending", False)),
        "title": getattr(m, "title", "") if m else "",
        "description": getattr(m, "description", "") if m else "",
        "hashtags": list(getattr(m, "hashtags", []) or []) if m else [],
    }})
Path(r"{out_path.as_posix()}").write_text(json.dumps(rows), encoding="utf-8")
print(len(rows))
"""
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(CLIPS_STUDIO_DIR),
                timeout=settings.kitty_llm_timeout,
            )
        except Exception as exc:
            raise RuntimeError(f"Gemma scoring failed to start: {exc}") from exc

        if proc.returncode != 0 or not out_path.exists():
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(friendly_gemma_error(detail))

        data = json.loads(out_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []


def friendly_gemma_error(detail: str) -> str:
    low = detail.lower()
    if "read timed out" in low or "readtimeout" in low or "timed out" in low:
        return (
            "Ollama timed out on Gemma. Chat spikes still used — "
            "try fewer clips or keep the VOD short on this PC."
        )
    if "connection" in low and ("refused" in low or "error" in low):
        return "Ollama not reachable — start Ollama, then retry with Gemma on."
    lines = [ln.strip() for ln in detail.splitlines() if ln.strip()]
    for ln in reversed(lines):
        if ln.startswith("File ") or ln.startswith("Traceback") or ln.startswith("~"):
            continue
        if "Error" in ln or "Exception" in ln or "failed" in ln.lower():
            return ln[-280:]
    return (lines[-1] if lines else "Gemma scoring failed")[-280:]


def kitty_picks_to_candidates(picks: list[dict]) -> list[ClipCandidate]:
    clips: list[ClipCandidate] = []
    for pick in picks:
        start = float(pick.get("start") or 0)
        end = float(pick.get("end") or 0)
        if end - start < 5:
            continue
        hook = str(pick.get("hook") or "").strip()
        reason = str(pick.get("reason") or "").strip()
        samples = [s for s in [hook, reason] if s][:5]
        clips.append(
            ClipCandidate(
                id=uuid.uuid4().hex[:10],
                start=round(start, 2),
                end=round(end, 2),
                peak_second=round((start + end) / 2, 2),
                score=round(float(pick.get("score") or 0), 2),
                sample_messages=samples,
                title=str(pick.get("title") or "") or None,
                description=str(pick.get("description") or "") or None,
                hashtags=list(pick.get("hashtags") or []),
                hook=hook or None,
                reason=reason or None,
                source="gemma",
                status="pending",
            )
        )
    return clips
