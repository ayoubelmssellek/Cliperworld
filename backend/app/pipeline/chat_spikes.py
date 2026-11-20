from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from app.config import settings
from app.models import ChatSpike


def load_chat_offsets(chat_path: Path) -> list[tuple[float, str]]:
    """Auto-detect TwitchDownloader JSON or yt-dlp live_chat JSON."""
    text = chat_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []

    # TwitchDownloader: one JSON object with comments[]
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and (data.get("comments") or data.get("Comments")):
                return _from_twitch(data)
        except json.JSONDecodeError:
            pass

    # yt-dlp live_chat: newline-delimited JSON actions
    return _from_youtube_live_chat(text)


def load_twitch_chat_offsets(chat_path: Path) -> list[tuple[float, str]]:
    return load_chat_offsets(chat_path)


def _from_twitch(data: dict) -> list[tuple[float, str]]:
    return [(t, text) for t, _who, text in _from_twitch_full(data)]


def _from_twitch_full(data: dict) -> list[tuple[float, str, str]]:
    comments = data.get("comments") or data.get("Comments") or []
    rows: list[tuple[float, str, str]] = []
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
        commenter = comment.get("commenter") or comment.get("Commenter") or {}
        if isinstance(commenter, dict):
            who = str(commenter.get("display_name") or commenter.get("name") or "chat")
        else:
            who = "chat"
        rows.append((float(offset), who, text.strip()))
    rows.sort(key=lambda r: r[0])
    return rows


def load_chat_with_authors(chat_path: Path) -> list[tuple[float, str, str]]:
    """[(offset, author, text)] for Clips Kitty chat_moments."""
    text = chat_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and (data.get("comments") or data.get("Comments")):
                return _from_twitch_full(data)
        except json.JSONDecodeError:
            pass
    # YouTube live chat: author unknown → "chat"
    return [(t, "chat", m) for t, m in _from_youtube_live_chat(text)]


def _from_youtube_live_chat(raw: str) -> list[tuple[float, str]]:
    rows: list[tuple[float, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # yt-dlp live_chat replay lines usually look like:
        # {"replayChatItemAction":{"actions":[...],"videoOffsetTimeMsec":"12345"}, ...}
        replay = obj.get("replayChatItemAction") or {}
        actions = replay.get("actions") or obj.get("actions") or []
        offset = _msec_to_seconds(
            replay.get("videoOffsetTimeMsec")
            or obj.get("videoOffsetTimeMsec")
        )

        for action in actions if isinstance(actions, list) else [actions]:
            if not isinstance(action, dict):
                continue
            item = (action.get("addChatItemAction") or {}).get("item") or {}
            renderer = (
                item.get("liveChatTextMessageRenderer")
                or item.get("liveChatPaidMessageRenderer")
                or item.get("liveChatMembershipItemRenderer")
                or {}
            )
            if not renderer:
                continue

            local_offset = offset
            if local_offset is None:
                continue

            runs = ((renderer.get("message") or {}).get("runs")) or []
            text = "".join(str(r.get("text") or "") for r in runs if isinstance(r, dict)).strip()
            if not text:
                amount = renderer.get("purchaseAmountText") or {}
                text = str(amount.get("simpleText") or "").strip()
            rows.append((float(local_offset), text))

    rows.sort(key=lambda r: r[0])
    return rows


def _msec_to_seconds(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return None


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
    Works for TwitchDownloader chat JSON and yt-dlp YouTube live_chat.
    """
    window = window_seconds if window_seconds is not None else settings.chat_window_seconds
    multiplier = spike_multiplier if spike_multiplier is not None else settings.chat_spike_multiplier
    min_msgs = min_messages if min_messages is not None else settings.chat_min_messages
    limit = max_spikes if max_spikes is not None else settings.max_clips

    events = load_chat_offsets(chat_path)
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

    # Clips Kitty chat_moments: POG / KEKW / CLIP IT class spikes (best-of)
    kitty_bonus: dict[int, float] = defaultdict(float)
    kitty_labels: dict[int, list[str]] = defaultdict(list)
    try:
        from app.pipeline.clips_studio import chat_hype_events

        duration = max((o for o, _ in events), default=0.0) + window
        full = load_chat_with_authors(chat_path)
        for ev in chat_hype_events(full, duration):
            sec = float(ev.get("second") or 0)
            bucket = int(sec // window)
            kitty_bonus[bucket] += 3.0
            label = str(ev.get("label") or "").strip()
            if label:
                kitty_labels[bucket].append(label[:80])
    except Exception:
        pass

    raw: list[ChatSpike] = []
    for bucket, msgs in buckets.items():
        count = len(msgs)
        if count < threshold and kitty_bonus.get(bucket, 0) <= 0:
            continue
        if count < max(4, min_msgs // 2) and kitty_bonus.get(bucket, 0) <= 0:
            continue
        peak = (bucket + 0.5) * window
        hype_bonus = sum(1 for m in msgs if any(t in m.lower() for t in hype_tokens))
        score = float(count) + hype_bonus * 0.75 + kitty_bonus.get(bucket, 0.0)
        samples = [m for m in msgs if m][:5]
        for label in kitty_labels.get(bucket, [])[:2]:
            if label not in samples:
                samples.insert(0, label)
        raw.append(
            ChatSpike(
                peak_second=peak,
                score=score,
                message_count=count,
                sample_messages=samples[:5],
            )
        )

    # Pure Clips Kitty chat-class peaks that our velocity gate would miss
    seen_buckets = {int(s.peak_second // window) for s in raw}
    for bucket, bonus in kitty_bonus.items():
        if bucket in seen_buckets or bonus <= 0:
            continue
        peak = (bucket + 0.5) * window
        labels = kitty_labels.get(bucket, [])[:5]
        raw.append(
            ChatSpike(
                peak_second=peak,
                score=float(bonus) + 8.0,
                message_count=max(1, int(bonus)),
                sample_messages=labels or ["chat hype"],
            )
        )

    raw.sort(key=lambda s: s.score, reverse=True)

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