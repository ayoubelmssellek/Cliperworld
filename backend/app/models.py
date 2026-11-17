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
    captioning = "captioning"
    done = "done"
    failed = "failed"


class CreateJobRequest(BaseModel):
    url: str = Field(
        ...,
        description="Twitch VOD or YouTube URL, e.g. https://www.twitch.tv/videos/123 or https://youtube.com/watch?v=...",
    )
    max_clips: int | None = Field(default=None, ge=1, le=30)
    with_captions: bool = True


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
    max_clips: int = 12
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