from __future__ import annotations

import re

from app.models import Platform
from app.pipeline.twitch import parse_twitch_vod_id

YOUTUBE_PATTERNS = [
    re.compile(r"(?:youtube\.com/watch\?.*?v=|youtu\.be/|youtube\.com/live/)([\w-]{6,})", re.I),
    re.compile(r"youtube\.com/shorts/([\w-]{6,})", re.I),
]


def detect_platform(url: str) -> Platform | None:
    text = (url or "").strip()
    if parse_twitch_vod_id(text):
        return Platform.twitch
    if parse_youtube_id(text):
        return Platform.youtube
    return None


def parse_youtube_id(url: str) -> str | None:
    text = (url or "").strip()
    for pattern in YOUTUBE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None