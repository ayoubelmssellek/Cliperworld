from __future__ import annotations

# Shared UI presets → platform-specific download settings
QUALITY_PRESETS = {
    "360": {
        "label": "360p (fast)",
        "twitch": "360p30",
        "youtube": "bv*[height<=360]+ba/b[height<=360]/b",
        "youtube_fallback": "b[height<=360]/b",
    },
    "480": {
        "label": "480p",
        "twitch": "480p30",
        "youtube": "bv*[height<=480]+ba/b[height<=480]/b",
        "youtube_fallback": "b[height<=480]/b",
    },
    "720": {
        "label": "720p (default)",
        "twitch": "720p60",
        "youtube": "bv*[height<=720]+ba/b[height<=720]/b",
        "youtube_fallback": "b[height<=720]/b[height<=480]/b",
    },
    "1080": {
        "label": "1080p",
        "twitch": "1080p60",
        "youtube": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "youtube_fallback": "b[height<=1080]/b[height<=720]/b",
    },
    "best": {
        "label": "Best available",
        "twitch": "Source",
        "youtube": "bv*+ba/b",
        "youtube_fallback": "b",
    },
}

DEFAULT_QUALITY = "720"


def normalize_quality(quality: str | None) -> str:
    key = (quality or DEFAULT_QUALITY).strip().lower()
    if key in QUALITY_PRESETS:
        return key
    # Allow raw aliases like "720p"
    key = key.replace("p", "")
    return key if key in QUALITY_PRESETS else DEFAULT_QUALITY


def twitch_quality(quality: str | None) -> str:
    return QUALITY_PRESETS[normalize_quality(quality)]["twitch"]


def youtube_format(quality: str | None) -> str:
    return QUALITY_PRESETS[normalize_quality(quality)]["youtube"]


def youtube_fallback_format(quality: str | None) -> str:
    return QUALITY_PRESETS[normalize_quality(quality)]["youtube_fallback"]


def quality_label(quality: str | None) -> str:
    return QUALITY_PRESETS[normalize_quality(quality)]["label"]