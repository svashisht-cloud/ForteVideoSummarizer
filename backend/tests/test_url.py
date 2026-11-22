import pytest

from app.pipeline.errors import InvalidURL
from app.pipeline.url import parse_video_id

ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        # watch URLs, with and without extra params
        f"https://www.youtube.com/watch?v={ID}",
        f"https://youtube.com/watch?v={ID}",
        f"http://www.youtube.com/watch?v={ID}",
        f"https://www.youtube.com/watch?v={ID}&t=42s",
        f"https://www.youtube.com/watch?v={ID}&list=PLabc123&index=3",
        f"https://www.youtube.com/watch?v={ID}&si=AbCdEf",
        f"https://www.youtube.com/watch?feature=share&v={ID}",
        f"https://www.youtube.com/watch/?v={ID}",
        f"https://www.youtube.com/watch?v={ID}#comments",
        # other hosts
        f"https://m.youtube.com/watch?v={ID}",
        f"https://music.youtube.com/watch?v={ID}&feature=share",
        f"https://WWW.YouTube.com/watch?v={ID}",
        # short links
        f"https://youtu.be/{ID}",
        f"https://youtu.be/{ID}?si=AbCdEf",
        f"https://youtu.be/{ID}?t=42",
        f"https://www.youtu.be/{ID}/",
        # path forms
        f"https://www.youtube.com/shorts/{ID}",
        f"https://youtube.com/shorts/{ID}?feature=share",
        f"https://www.youtube.com/live/{ID}",
        f"https://www.youtube.com/live/{ID}?si=xyz",
        f"https://www.youtube.com/embed/{ID}",
        f"https://www.youtube.com/embed/{ID}?start=10",
        f"https://m.youtube.com/shorts/{ID}/",
        # no scheme
        f"youtube.com/watch?v={ID}",
        f"www.youtube.com/watch?v={ID}&t=1",
        f"m.youtube.com/watch?v={ID}",
        f"youtu.be/{ID}",
        f"youtube.com/shorts/{ID}",
        # bare ID, and surrounding whitespace
        ID,
        f"  {ID}\n",
        f"  https://youtu.be/{ID}  ",
    ],
)
def test_accepts(url):
    assert parse_video_id(url) == ID


@pytest.mark.parametrize("video_id", ["abc_DEF-123", "-----------", "___________", "A1b2C3d4E5f"])
def test_id_charset(video_id):
    assert parse_video_id(video_id) == video_id
    assert parse_video_id(f"https://youtu.be/{video_id}") == video_id


@pytest.mark.parametrize(
    "url, message_part",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("hello", "not a URL or an 11-character video ID"),
        ("dQw4w9WgXc", "not a URL or an 11-character video ID"),  # 10 chars
        ("https://vimeo.com/123456", "not a YouTube URL"),
        (f"https://notyoutube.com/watch?v={ID}", "not a YouTube URL"),
        (f"https://youtube.com.evil.com/watch?v={ID}", "not a YouTube URL"),
        (f"ftp://youtube.com/watch?v={ID}", "scheme"),
        ("https://www.youtube.com/watch", "missing the v= parameter"),
        ("https://www.youtube.com/watch?list=PLabc", "missing the v= parameter"),
        ("https://www.youtube.com/watch?v=", "missing the v= parameter"),
        ("https://www.youtube.com/watch?v=short", "invalid video ID"),
        (f"https://www.youtube.com/watch?v={ID}X", "invalid video ID"),  # 12 chars
        ("https://www.youtube.com/watch?v=dQw4w9WgX!Q", "invalid video ID"),
        ("https://youtu.be/", "no video ID"),
        ("https://youtu.be/abc", "invalid video ID"),
        ("https://www.youtube.com/shorts/", "no video ID"),
        ("https://www.youtube.com/embed/abc", "invalid video ID"),
        ("https://www.youtube.com/", "unsupported YouTube URL"),
        ("https://www.youtube.com/@somechannel", "unsupported YouTube URL"),
        ("https://www.youtube.com/playlist?list=PLabc", "unsupported YouTube URL"),
        (f"https://www.youtube.com/shorts/{ID}/extra", "unsupported YouTube URL"),
    ],
)
def test_rejects_with_reason(url, message_part):
    with pytest.raises(InvalidURL) as exc:
        parse_video_id(url)
    assert message_part in str(exc.value)


def test_invalid_url_is_value_error():
    # Lets callers that only know about ValueError still catch it.
    assert issubclass(InvalidURL, ValueError)
