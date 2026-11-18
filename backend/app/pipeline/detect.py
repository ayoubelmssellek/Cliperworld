from __future__ import annotations

import re

from app.models import Platform
from app.pipeline.twitch import parse_twitch_vod_id

YOUTUBE_PATTERNS = [
    re.compile(r"(?:youtube\.com/watch\?.*?v=|youtu\.be/|youtube\.com/live/)([\w-]{6,})", re.I),
    re.compile(r"youtube\.com/shorts/([\w-]{6,})", re.I),
]

TWITCH_CHANNEL_RE = re.compile(
    r"^(?:https?://)?(?:www\.|m\.)?twitch\.tv/([A-Za-z0-9_]{3,25})/?$",
    re.I,
)
TWITCH_RESERVED = {
    "videos",
    "directory",
    "downloads",
    "jobs",
    "settings",
    "inventory",
    "subscriptions",
    "wallet",
    "p",
    "popout",
    "embed",
    "login",
    "signup",
    "search",
}


def detect_platform(url: str) -> Platform | None:
    text = (url or "").strip()
    if parse_twitch_vod_id(text) or parse_twitch_channel(text):
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


def parse_twitch_channel(url: str) -> str | None:
    """Return channel login for https://www.twitch.tv/lacy (not a VOD URL)."""
    text = (url or "").strip().split("?")[0].rstrip("/")
    match = TWITCH_CHANNEL_RE.match(text)
    if not match:
        return None
    login = match.group(1)
    if login.lower() in TWITCH_RESERVED:
        return None
    return login


def normalize_input_url(url: str) -> tuple[str, Platform, dict]:
    """
    Normalize user paste into a concrete media URL.
    Twitch channel pages → latest VOD.
    """
    text = (url or "").strip()
    platform = detect_platform(text)
    if platform is None:
        raise ValueError(
            "Paste a Twitch VOD (twitch.tv/videos/…), Twitch channel, or YouTube link."
        )

    meta: dict = {"original_url": text}

    if platform == Platform.twitch:
        if parse_twitch_vod_id(text):
            return text, platform, meta
        channel = parse_twitch_channel(text)
        if not channel:
            raise ValueError(
                "That Twitch link isn’t a VOD or channel. Example: https://www.twitch.tv/videos/123456789"
            )
        from app.pipeline.twitch import resolve_latest_vod_from_channel

        vod_url, vod_id = resolve_latest_vod_from_channel(channel)
        meta.update({"resolved_from_channel": channel, "vod_id": vod_id})
        return vod_url, platform, meta

    return text, platform, meta