from app.pipeline.detect import detect_platform, parse_twitch_channel, parse_youtube_id
from app.models import Platform


def test_detect_twitch():
    assert detect_platform("https://www.twitch.tv/videos/2928036561") == Platform.twitch


def test_detect_twitch_channel():
    assert parse_twitch_channel("https://www.twitch.tv/lacy") == "lacy"
    assert detect_platform("https://www.twitch.tv/lacy") == Platform.twitch


def test_detect_youtube():
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert parse_youtube_id(url) == "dQw4w9WgXcQ"
    assert detect_platform(url) == Platform.youtube


def test_detect_youtu_be():
    assert parse_youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"