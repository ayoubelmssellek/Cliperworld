from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from app.config import settings
from app.models import ChatSpike


def load_twitch_chat_offsets(chat_path: Path) -> list[tuple[float, str]]:
    """
    Parse TwitchDownloader chat JSON into (offset_seconds, message_text).
    Supports common TwitchDownloader comment shapes.
    """
    data = json.loads(chat_path.read_text(encoding="utf-8"))
    comments = data.get("comments") or data.get("Comments") or []
    rows: list[tuple[float, str]] = []

    for comment in comments:
        offset = (
            comment.get("content_offset_seconds")
            or comment.get("contentOffsetSeconds")
            or comment.get("offset")
        )
        if offset is None:
            continue
        message = comment.get("message") or {}
        if isinstance(message, dict):
            text = message.get("body") or message.get("Body") or ""
        else:
            text = str(message)
        rows.append((float(offset), text.strip()))

    rows.sort(key=lambda r: r[0])
    return rows


def detect_chat_spikes(
    chat_path: Path,
    *,
    window_seconds: float | None = None,
    spike_multiplier: float | None = None,
    min_messages: int | None = None,
    max_spikes: int | None = None,
) -> list[ChatSpike]:
    """
    Find moments where chat 'blows up' vs the stream baseline.
    No AI required — message velocity + simple hype keywords.
    """
    window = window_seconds if window_seconds is not None else settings.chat_window_seconds
    multiplier = spike_multiplier if spike_multiplier is not None else settings.chat_spike_multiplier
    min_msgs = min_messages if min_messages is not None else settings.chat_min_messages
    limit = max_spikes if max_spikes is not None else settings.max_clips

    events = load_twitch_chat_offsets(chat_path)
    if not events:
        return []

    buckets: dict[int, list[str]] = defaultdict(list)
    for offset, text in events:
        bucket = int(offset // window)
        buckets[bucket].append(text)

    if not buckets:
        return []

    counts = [len(msgs) for msgs in buckets.values()]
    baseline = sorted(counts)[len(counts) // 2] or 1
    threshold = max(min_msgs, baseline * multiplier)

    hype_tokens = {
        "clip",
        "clips",
        "omg",
        "wtf",
        "lmao",
        "lol",
        "kekw",
        "pog",
        "poggers",
        "no way",
        "holy",
        "insane",
        "dude",
        "bro",
    }

    raw: list[ChatSpike] = []
    for bucket, msgs in buckets.items():
        count = len(msgs)
        if count < threshold:
            continue
        peak = (bucket + 0.5) * window
        hype_bonus = sum(1 for m in msgs if any(t in m.lower() for t in hype_tokens))
        score = float(count) + hype_bonus * 0.75
        samples = [m for m in msgs if m][:5]
        raw.append(
            ChatSpike(
                peak_second=peak,
                score=score,
                message_count=count,
                sample_messages=samples,
            )
        )

    raw.sort(key=lambda s: s.score, reverse=True)

    # Suppress overlapping peaks (keep stronger)
    selected: list[ChatSpike] = []
    min_gap = settings.clip_pre_seconds + settings.clip_post_seconds
    for spike in raw:
        if any(abs(spike.peak_second - kept.peak_second) < min_gap for kept in selected):
            continue
        selected.append(spike)
        if len(selected) >= limit:
            break

    selected.sort(key=lambda s: s.peak_second)
    return selected