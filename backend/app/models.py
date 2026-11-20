from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Platform(str, Enum):
    twitch = "twitch"
    youtube = "youtube"  # later
    kick = "kick"  # later


class JobStatus(str, Enum):
    queued = "queued"
    downloading = "downloading"
    analyzing_chat = "analyzing_chat"
    cutting = "cutting"
    shorts = "shorts"
    captioning = "captioning"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


LAYOUT_PRESETS = ("blur", "full_hook", "cam_hook_game", "game_hook_cam", "face")


class ReframeClipRequest(BaseModel):
    cam_zoom: float = Field(default=1.0, ge=0.7, le=1.5)
    game_zoom: float = Field(default=1.0, ge=1.0, le=2.0)
    game_pan: float = Field(default=0.55, ge=0.0, le=1.0)
    layout: str | None = Field(
        default=None,
        description="Optional layout override: cam_hook_game | game_hook_cam",
    )


class CaptionStyleRequest(BaseModel):
    alignment: str = Field(default="bottom", description="top | middle | bottom")
    font_name: str = Field(default="Anton")
    font_size: int = Field(default=40, ge=18, le=90)
    font_color: str = Field(default="#FFFFFF")
    highlight_color: str = Field(default="#FFE500")
    margin_v: int = Field(default=43, ge=8, le=120)
    uppercase: bool = True
    effect: str = Field(default="pop", description="none | pop | glow | highlight")


class CreateJobRequest(BaseModel):
    url: str = Field(
        ...,
        description="Twitch VOD or YouTube URL, e.g. https://www.twitch.tv/videos/123 or https://youtube.com/watch?v=...",
    )
    max_clips: int | None = Field(default=None, ge=1, le=30)
    with_captions: bool = True
    with_gemma: bool = True
    quality: str = Field(
        default="720",
        description="Download quality preset: 360, 480, 720, 1080, or best",
    )
    layout: str = Field(
        default="blur",
        description="Shorts layout: blur | full_hook | cam_hook_game | game_hook_cam | face",
    )
    cam_zoom: float = Field(
        default=1.0,
        ge=0.7,
        le=1.5,
        description="Facecam framing: <1 more room around streamer, >1 tighter on face",
    )
    game_zoom: float = Field(
        default=1.0,
        ge=1.0,
        le=2.0,
        description="Gameplay zoom inside the phone: 1.0 wide/clear FOV, higher = dig into action",
    )
    game_pan: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Gameplay horizontal pan 0=left … 1=right (what you see in the phone)",
    )


class ChatSpike(BaseModel):
    peak_second: float
    score: float
    message_count: int
    sample_messages: list[str] = []


class ClipCandidate(BaseModel):
    id: str
    start: float
    end: float
    peak_second: float
    score: float
    sample_messages: list[str] = []
    video_path: str | None = None
    captioned_path: str | None = None
    status: str = "pending"
    # Clips Kitty / Gemma metadata (when Ollama is available)
    title: str | None = None
    description: str | None = None
    hashtags: list[str] = []
    hook: str | None = None
    reason: str | None = None
    source: str = "chat"  # chat | gemma | audio


class Job(BaseModel):
    id: str
    url: str
    platform: Platform
    status: JobStatus
    message: str = ""
    vod_id: str | None = None
    video_path: str | None = None
    chat_path: str | None = None
    spikes: list[ChatSpike] = []
    clips: list[ClipCandidate] = []
    with_captions: bool = True
    with_gemma: bool = True
    max_clips: int = 12
    quality: str = "720"
    layout: str = "blur"
    cam_zoom: float = 1.0
    game_zoom: float = 1.0
    game_pan: float = 0.55
    error: str | None = None
    created_at: float
    updated_at: float
    meta: dict[str, Any] = {}


class JobResponse(BaseModel):
    job: Job


class HealthResponse(BaseModel):
    ok: bool
    app: str
    tools: dict[str, bool]