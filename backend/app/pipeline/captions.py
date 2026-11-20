from __future__ import annotations

"""
Captions via OpenShorts karaoke ASS (vendor/openshorts/subtitles.py):
  word-level Whisper timestamps → yellow active-word pop → burned with libass.

Not a full-sentence SRT dump — that covered the whole Short. This matches
OpenShorts' AUTO_CAPTION_STYLE (Anton, bottom-safe, ~1–3 words/line).
"""

import subprocess
import sys
from pathlib import Path

from app.config import settings
from app.paths import OPENSHORTS_DIR

_model = None
_last_error: str | None = None


def last_caption_error() -> str | None:
    return _last_error


def default_caption_style() -> dict:
    return {
        "alignment": "bottom",
        "font_name": "Anton",
        "font_size": 40,
        "font_color": "#FFFFFF",
        "highlight_color": "#FFE500",
        "border_color": "#000000",
        "border_width": 2,
        "effect": "pop",
        "base_opacity": 1.0,
        "uppercase": True,
        "max_chars": 18,
        "max_duration": 1.4,
        "margin_v": 43,
    }


def caption_clip(
    clip_path: Path, job_dir: Path, style: dict | None = None
) -> Path | None:
    global _last_error
    _last_error = None

    out_path = job_dir / f"captioned_{clip_path.name}"
    if OPENSHORTS_DIR.exists():
        burned = _caption_openshorts_karaoke(clip_path, job_dir, out_path, style=style)
        if burned:
            return burned

    # Fallback: short-line SRT (still better than one giant block)
    srt = _transcribe_to_short_srt(clip_path, job_dir)
    if not srt:
        return None
    return _burn_srt(clip_path, srt, out_path)


def recaption_clip(
    clip_path: Path, job_dir: Path, style: dict | None = None
) -> Path | None:
    """Re-burn captions from cached word timestamps (no re-transcribe)."""
    global _last_error
    _last_error = None
    work = job_dir / "transcript"
    words_json = work / f"{clip_path.stem}.words.json"
    if not words_json.exists():
        _last_error = "No caption transcript cached — regenerate the Short first"
        return None
    out_path = job_dir / f"captioned_{clip_path.name}"
    return _caption_openshorts_karaoke(
        clip_path, job_dir, out_path, style=style, reuse_words=True
    )


def _get_model():
    global _model, _last_error
    if _model is not None:
        return _model
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        _last_error = (
            "faster-whisper is not installed. Run: python -m pip install faster-whisper"
        )
        raise RuntimeError(_last_error) from exc

    model_size = settings.whisper_model
    _model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _model


def _caption_openshorts_karaoke(
    clip_path: Path,
    job_dir: Path,
    out_path: Path,
    style: dict | None = None,
    reuse_words: bool = False,
) -> Path | None:
    """Word-by-word ASS via OpenShorts generate_ass + ffmpeg ass filter."""
    global _last_error
    work = job_dir / "transcript"
    work.mkdir(parents=True, exist_ok=True)
    words_json = work / f"{clip_path.stem}.words.json"

    if reuse_words and words_json.exists():
        transcript = None
    else:
        transcript = _transcribe_word_transcript(clip_path, job_dir)
        if not transcript:
            return None
        words_json.write_text(
            __import__("json").dumps(transcript),
            encoding="utf-8",
        )

    if not words_json.exists():
        _last_error = "Missing word timestamps for captions"
        return None

    ass_path = work / f"{clip_path.stem}.ass"
    fonts_dir = OPENSHORTS_DIR / "fonts"
    style_path = work / f"{clip_path.stem}.style.json"
    merged = default_caption_style()
    if isinstance(style, dict):
        merged.update({k: v for k, v in style.items() if v is not None})
    style_path.write_text(__import__("json").dumps(merged), encoding="utf-8")

    script = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, r"{OPENSHORTS_DIR.as_posix()}")
from subtitles import generate_ass, AUTO_CAPTION_STYLE

payload = json.loads(Path(r"{words_json.as_posix()}").read_text(encoding="utf-8"))
raw = dict(AUTO_CAPTION_STYLE)
raw.update(json.loads(Path(r"{style_path.as_posix()}").read_text(encoding="utf-8")))
raw.pop("style", None)
if "font_size" in raw and "fontsize" not in raw:
    raw["fontsize"] = raw.pop("font_size")
ok = generate_ass(
    payload,
    0.0,
    float(payload.get("duration") or 999),
    r"{ass_path.as_posix()}",
    **raw,
)
print("ok" if ok else "empty")
"""

    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(OPENSHORTS_DIR),
            timeout=120,
        )
    except Exception as exc:
        _last_error = f"OpenShorts ASS failed: {exc}"
        return None

    if proc.returncode != 0 or not ass_path.exists():
        detail = (proc.stderr or proc.stdout or "").strip()
        _last_error = f"OpenShorts ASS failed: {detail[-500:] or proc.returncode}"
        return None
    if "empty" in (proc.stdout or ""):
        _last_error = "No speech for karaoke captions"
        return None

    return _burn_ass(clip_path, ass_path, out_path, fonts_dir)


def _transcribe_word_transcript(clip_path: Path, job_dir: Path) -> dict | None:
    global _last_error
    work = job_dir / "transcript"
    work.mkdir(parents=True, exist_ok=True)
    wav_path = work / f"{clip_path.stem}.wav"
    if not _extract_wav(clip_path, wav_path):
        return None

    try:
        model = _get_model()
        audio = _load_wav_f32(wav_path)
        segments, _info = model.transcribe(
            audio,
            language=None,
            vad_filter=True,
            word_timestamps=True,
        )
        out_segments: list[dict] = []
        duration = 0.0
        for seg in segments:
            words = []
            for w in seg.words or []:
                text = (w.word or "").strip()
                if not text:
                    continue
                # OpenShorts merge_continuation_words expects leading space on new words
                words.append(
                    {
                        "word": f" {text}",
                        "start": float(w.start),
                        "end": float(w.end),
                    }
                )
                duration = max(duration, float(w.end))
            if words:
                out_segments.append(
                    {
                        "start": float(seg.start),
                        "end": float(seg.end),
                        "text": (seg.text or "").strip(),
                        "words": words,
                    }
                )
        if not out_segments:
            _last_error = "No speech detected in clip"
            return None
        return {"segments": out_segments, "duration": duration}
    except Exception as exc:
        _last_error = f"Transcription failed: {exc}"
        return None


def _transcribe_to_short_srt(clip_path: Path, job_dir: Path) -> Path | None:
    """Fallback: short chunks (not one giant sentence)."""
    global _last_error
    transcript = _transcribe_word_transcript(clip_path, job_dir)
    if not transcript:
        return None

    words: list[dict] = []
    for seg in transcript["segments"]:
        for w in seg.get("words") or []:
            words.append(
                {
                    "word": (w.get("word") or "").strip(),
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                }
            )
    if not words:
        return None

    work = job_dir / "transcript"
    srt_path = work / f"{clip_path.stem}.srt"
    max_chars = 22
    max_dur = 1.6
    blocks: list[list[dict]] = []
    current: list[dict] = []
    block_start = 0.0
    for w in words:
        if not current:
            current = [w]
            block_start = w["start"]
            continue
        text_len = sum(len(x["word"]) + 1 for x in current)
        if text_len + len(w["word"]) > max_chars or (w["end"] - block_start) > max_dur:
            blocks.append(current)
            current = [w]
            block_start = w["start"]
        else:
            current.append(w)
    if current:
        blocks.append(current)

    lines: list[str] = []
    for i, block in enumerate(blocks, start=1):
        text = " ".join(x["word"] for x in block).strip()
        lines.append(str(i))
        lines.append(f"{_ts(block[0]['start'])} --> {_ts(block[-1]['end'])}")
        lines.append(text)
        lines.append("")
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return srt_path


def _load_wav_f32(wav_path: Path):
    import wave

    import numpy as np

    with wave.open(str(wav_path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        frames = handle.readframes(handle.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _extract_wav(clip_path: Path, wav_path: Path) -> bool:
    global _last_error
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(clip_path),
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
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr if isinstance(exc.stderr, str) else ""
        _last_error = f"Audio extract failed: {detail[-300:]}"
        return False


def _escape_ffmpeg_path(path: Path) -> str:
    # FFmpeg filter paths: forward slashes, escape drive colon and quotes
    text = path.resolve().as_posix()
    text = text.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return text


def _burn_ass(
    clip_path: Path, ass_path: Path, out_path: Path, fonts_dir: Path
) -> Path | None:
    global _last_error
    ass_esc = _escape_ffmpeg_path(ass_path)
    fonts_esc = _escape_ffmpeg_path(fonts_dir) if fonts_dir.exists() else ""
    if fonts_esc:
        vf = f"ass=filename='{ass_esc}':fontsdir='{fonts_esc}'"
    else:
        vf = f"ass=filename='{ass_esc}'"
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(clip_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(out_path),
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
        if out_path.exists() and out_path.stat().st_size > 0:
            return out_path
        _last_error = "FFmpeg produced empty captioned file"
        return None
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "")[-600:]
        _last_error = f"FFmpeg ASS burn failed: {detail}"
        return None


def _burn_srt(clip_path: Path, srt_path: Path, out_path: Path) -> Path | None:
    global _last_error
    srt_escaped = _escape_ffmpeg_path(srt_path)
    # Compact bottom captions — never dump a paragraph mid-frame
    style = (
        "FontName=Arial,FontSize=16,Bold=1,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=48"
    )
    vf = f"subtitles=filename='{srt_escaped}':force_style='{style}'"
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-i",
        str(clip_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "copy",
        str(out_path),
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
        if out_path.exists() and out_path.stat().st_size > 0:
            return out_path
        _last_error = "FFmpeg produced empty captioned file"
        return None
    except subprocess.CalledProcessError as exc:
        _last_error = f"FFmpeg burn failed: {(exc.stderr or '')[-500:]}"
        return None


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
