"""Unit tests for stt.py. No network, no ffmpeg, no models: all faked."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.pipeline import stt
from app.pipeline.errors import PipelineError, VideoUnavailable, YouTubeBlocked
from app.pipeline.models import Segment
from app.pipeline.stt import (
    engine_name,
    map_ytdlp_error,
    normalize_language,
    offset_segments,
    plan_pieces,
    to_segments,
    transcribe,
)


# --- to_segments / offset_segments ---------------------------------------------


def test_to_segments_converts_and_strips():
    raw = [{"start": 0.0, "end": 2.5, "text": " Hello "}, {"start": 2.5, "end": 4.0, "text": "world"}]
    assert to_segments(raw) == [Segment(start=0, end=2.5, text="Hello"), Segment(start=2.5, end=4, text="world")]


def test_to_segments_skips_empty_and_clamps_end():
    raw = [
        {"start": 0.0, "end": 1.0, "text": "   "},
        {"start": 5.0, "end": 4.9, "text": "backwards"},
        {"start": -0.01, "end": 1.0, "text": "early"},
    ]
    assert to_segments(raw) == [
        Segment(start=5.0, end=5.0, text="backwards"),
        Segment(start=0.0, end=1.0, text="early"),
    ]


def test_offset_segments():
    segs = [Segment(start=0, end=2, text="a"), Segment(start=3, end=4, text="b")]
    assert offset_segments(segs, 600) == [Segment(start=600, end=602, text="a"), Segment(start=603, end=604, text="b")]
    assert offset_segments(segs, 0) == segs


# --- plan_pieces ---------------------------------------------------------------------


def test_plan_pieces_under_limits_is_one_piece():
    assert plan_pieces(3600, 10_000_000, max_bytes=24_000_000, max_seconds=7200) == [(0.0, 3600.0)]


def test_plan_pieces_caps_piece_duration():
    # Long requests get cut by ~60s idle timeouts; whisper-1 takes ~2.5s per audio minute.
    pieces = plan_pieces(3600, 10_000_000, max_bytes=24_000_000, max_seconds=600)
    assert pieces == [(i * 600.0, 600.0) for i in range(6)]


def test_plan_pieces_uses_whichever_limit_needs_more_pieces():
    assert len(plan_pieces(1200, 60_000_000, max_bytes=24_000_000, max_seconds=600)) == 3  # size wins
    assert len(plan_pieces(3600, 30_000_000, max_bytes=24_000_000, max_seconds=600)) == 6  # duration wins


def test_plan_pieces_splits_evenly_and_covers_duration():
    pieces = plan_pieces(3600, 60_000_000, max_bytes=24_000_000, max_seconds=7200)  # 2.5x the limit
    assert len(pieces) == 3
    assert pieces[0][0] == 0
    for (s1, l1), (s2, _) in zip(pieces, pieces[1:]):
        assert s1 + l1 == pytest.approx(s2)  # no gaps, no overlap
    last_start, last_len = pieces[-1]
    assert last_start + last_len == pytest.approx(3600)


def test_plan_pieces_leaves_margin_near_limit():
    # Exactly at the limit: pieces cut with -c copy can come out slightly
    # bigger than the even share, so split anyway.
    assert len(plan_pieces(3600, 24_000_000, max_bytes=24_000_000, max_seconds=7200)) == 2


# --- normalize_language -------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("english", "en"),
        ("English", "en"),
        ("en", "en"),
        ("swahili", "sw"),
        ("castilian", "es"),  # Whisper alias
        ([{"code": "fr"}], "fr"),
        ([SimpleNamespace(code="de")], "de"),
    ],
)
def test_normalize_language(value, expected):
    assert normalize_language(value) == expected


@pytest.mark.parametrize("value", [None, "", [], "klingon"])
def test_normalize_language_unknown(value):
    assert normalize_language(value) == "und"


# --- map_ytdlp_error ----------------------------------------------------------------


@pytest.mark.parametrize(
    "msg, expected",
    [
        ("ERROR: [youtube] abc: Sign in to confirm you’re not a bot. Use --cookies", YouTubeBlocked),
        ("ERROR: unable to download video data: HTTP Error 429: Too Many Requests", YouTubeBlocked),
        ("ERROR: [youtube] abc: Video unavailable. This video has been removed", VideoUnavailable),
        ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", VideoUnavailable),
        ("ERROR: [youtube] abc: Sign in to confirm your age.", VideoUnavailable),
        ("ERROR: [youtube] abc: Join this channel to get access to members-only content", VideoUnavailable),
        ("ERROR: something else broke", PipelineError),
    ],
)
def test_map_ytdlp_error(msg, expected):
    err = map_ytdlp_error("abc", msg)
    assert type(err) is expected
    assert "abc" in str(err)


# --- engine selection ---------------------------------------------------------------


@pytest.fixture
def fake_engines(monkeypatch):
    calls = []
    monkeypatch.setattr(stt, "transcribe_local", lambda p: calls.append(("local", p)) or ([], "en"))
    monkeypatch.setattr(stt, "transcribe_openai", lambda p, client=None: calls.append(("openai", p, client)) or ([], "en"))
    return calls


def test_engine_defaults_to_local(monkeypatch, fake_engines):
    monkeypatch.delenv("STT_ENGINE", raising=False)
    assert engine_name() == "local"
    transcribe(Path("a.m4a"))
    assert fake_engines == [("local", Path("a.m4a"))]


def test_engine_openai(monkeypatch, fake_engines):
    monkeypatch.setenv("STT_ENGINE", " OpenAI ")
    assert engine_name() == "openai"
    transcribe(Path("a.m4a"), openai_client="user-client")
    assert fake_engines == [("openai", Path("a.m4a"), "user-client")]


def test_engine_unknown_raises(monkeypatch, fake_engines):
    monkeypatch.setenv("STT_ENGINE", "cloud")
    with pytest.raises(PipelineError, match="STT_ENGINE"):
        transcribe(Path("a.m4a"))
    assert fake_engines == []


# --- openai engine (client, ffmpeg and ffprobe faked) ----------------------------------


class FakeTranscriptions:
    """Answers by upload order of the *pieces* (file names sort by index), not by
    call order, since pieces are uploaded concurrently."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.lock = threading.Lock()

    def create(self, **kwargs):
        name = Path(kwargs["file"].name).name
        with self.lock:
            self.calls.append({k: v for k, v in kwargs.items() if k != "file"} | {"name": name})
        time.sleep(0.01)
        index = int(name.removeprefix("piece").removesuffix(".ogg")) if name.startswith("piece") else 0
        return self.responses[index]


def verbose(language, segments):
    return SimpleNamespace(
        language=language,
        segments=[SimpleNamespace(start=s, end=e, text=t) for s, e, t in segments],
    )


@pytest.fixture
def fake_ffmpeg(monkeypatch, tmp_path):
    """compress -> writes N bytes; probe -> fixed duration; cut -> writes a piece file."""
    cuts = []

    def compress(src, dst):
        dst.write_bytes(b"x" * 50)

    def cut(src, start, length, dst):
        cuts.append((start, length))
        dst.write_bytes(b"x")

    monkeypatch.setattr(stt, "_compress", compress)
    monkeypatch.setattr(stt, "_probe_duration", lambda p: 900.0)
    monkeypatch.setattr(stt, "_cut", cut)
    return cuts


def test_openai_single_piece(tmp_path, fake_ffmpeg):
    audio = tmp_path / "in.webm"
    audio.write_bytes(b"audio")
    api = FakeTranscriptions([verbose("english", [(0, 2, " hi "), (2, 4, "there")])])
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=api))

    segs, lang = stt.transcribe_openai(audio, client=client, model="whisper-1", max_bytes=1000, max_seconds=1000)

    assert lang == "en"
    assert segs == [Segment(start=0, end=2, text="hi"), Segment(start=2, end=4, text="there")]
    assert fake_ffmpeg == []
    (call,) = api.calls
    assert call["model"] == "whisper-1"
    assert call["response_format"] == "verbose_json"
    assert call["timestamp_granularities"] == ["segment"]
    assert call["name"].endswith(".ogg")


def test_openai_split_offsets_timestamps(tmp_path, fake_ffmpeg):
    audio = tmp_path / "in.webm"
    audio.write_bytes(b"audio")
    api = FakeTranscriptions(
        [
            verbose("english", [(0, 5, "one")]),
            verbose("english", [(1, 3, "two")]),
            verbose("english", [(0, 2, "three")]),
        ]
    )
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=api))

    # 50 compressed bytes over a 20-byte limit -> 3 pieces of 300s.
    segs, lang = stt.transcribe_openai(audio, client=client, model="whisper-1", max_bytes=20)

    assert fake_ffmpeg == [(0.0, 300.0), (300.0, 300.0), (600.0, 300.0)]
    assert [(s.start, s.end, s.text) for s in segs] == [(0, 5, "one"), (301, 303, "two"), (600, 602, "three")]
    assert lang == "en"
    assert sorted(c["name"] for c in api.calls) == ["piece000.ogg", "piece001.ogg", "piece002.ogg"]


def test_openai_long_audio_split_by_duration(tmp_path, fake_ffmpeg):
    audio = tmp_path / "in.webm"
    audio.write_bytes(b"audio")
    api = FakeTranscriptions([verbose("english", [(0, 1, f"p{i}")]) for i in range(3)])
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=api))
    # 900s under a 300s cap -> 3 pieces even though the size is tiny.
    segs, _ = stt.transcribe_openai(audio, client=client, model="whisper-1", max_bytes=10**9, max_seconds=300)
    assert [(s.start, s.text) for s in segs] == [(0, "p0"), (300, "p1"), (600, "p2")]


def test_openai_missing_segments_raises(tmp_path, fake_ffmpeg):
    audio = tmp_path / "in.webm"
    audio.write_bytes(b"audio")
    api = FakeTranscriptions([SimpleNamespace(language="english", segments=None)])
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=api))
    with pytest.raises(PipelineError, match="segment timestamps"):
        stt.transcribe_openai(audio, client=client, model="some-model", max_bytes=1000, max_seconds=1000)


def test_openai_model_from_env(monkeypatch, tmp_path, fake_ffmpeg):
    monkeypatch.setenv("OPENAI_STT_MODEL", "env-stt-model")
    audio = tmp_path / "in.webm"
    audio.write_bytes(b"audio")
    api = FakeTranscriptions([verbose("english", [(0, 1, "x")])])
    stt.transcribe_openai(
        audio, client=SimpleNamespace(audio=SimpleNamespace(transcriptions=api)), max_bytes=1000, max_seconds=1000
    )
    assert api.calls[0]["model"] == "env-stt-model"


def test_openai_model_default_is_whisper_1(monkeypatch):
    monkeypatch.delenv("OPENAI_STT_MODEL", raising=False)
    assert stt.openai_stt_model() == "whisper-1"


# --- video_language (yt-dlp metadata, no download) ------------------------------------


class FakeYDL:
    info: dict | None = None
    error: Exception | None = None
    opts: dict = {}

    def __init__(self, opts):
        FakeYDL.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        assert download is False
        if FakeYDL.error:
            raise FakeYDL.error
        return FakeYDL.info


@pytest.fixture
def ydl(monkeypatch):
    FakeYDL.info, FakeYDL.error = None, None
    monkeypatch.setattr(stt.yt_dlp, "YoutubeDL", FakeYDL)
    return FakeYDL


def test_video_language_reads_metadata(ydl):
    ydl.info = {"language": "en-US"}
    assert stt.video_language("dQw4w9WgXcQ") == "en-US"
    assert ydl.opts.get("skip_download") is True


def test_video_language_missing_is_none(ydl):
    ydl.info = {}
    assert stt.video_language("dQw4w9WgXcQ") is None


@pytest.mark.parametrize(
    "msg, expected",
    [
        ("ERROR: Sign in to confirm you're not a bot", YouTubeBlocked),
        ("ERROR: [youtube] x: Private video", VideoUnavailable),
        ("ERROR: something else", PipelineError),
    ],
)
def test_video_language_maps_errors(ydl, msg, expected):
    ydl.error = stt.yt_dlp.utils.DownloadError(msg)
    with pytest.raises(expected):
        stt.video_language("dQw4w9WgXcQ")


def test_video_metadata_reads_title_language_and_chapters(ydl):
    ydl.info = {
        "title": "How to never procrastinate",
        "language": "en-US",
        "chapters": [
            {"title": "Intro", "start_time": 0.0, "end_time": 61.5},
            {"title": "The loop", "start_time": 61.5, "end_time": None},
            {"title": "broken"},  # no start: skipped
        ],
    }
    meta = stt.video_metadata("dQw4w9WgXcQ")
    assert (meta.title, meta.language) == ("How to never procrastinate", "en-US")
    assert [(c.title, c.start, c.end) for c in meta.chapters] == [("Intro", 0.0, 61.5), ("The loop", 61.5, None)]


def test_video_metadata_without_chapters(ydl):
    ydl.info = {"title": "x"}
    assert stt.video_metadata("dQw4w9WgXcQ").chapters == []
