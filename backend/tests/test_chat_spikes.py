import json
from pathlib import Path

from app.pipeline.chat_spikes import detect_chat_spikes


def test_detects_blow_up(tmp_path: Path):
    comments = []
    # quiet baseline
    for i in range(40):
        comments.append(
            {
                "content_offset_seconds": float(i),
                "message": {"body": "hi"},
            }
        )
    # blow-up around second 120
    for i in range(40):
        comments.append(
            {
                "content_offset_seconds": 120.0 + i * 0.15,
                "message": {"body": "CLIP THAT KEKW"},
            }
        )

    chat = tmp_path / "chat.json"
    chat.write_text(json.dumps({"comments": comments}), encoding="utf-8")
    spikes = detect_chat_spikes(chat, window_seconds=8, spike_multiplier=2.0, min_messages=8, max_spikes=3)
    assert spikes
    assert 100 < spikes[0].peak_second < 140