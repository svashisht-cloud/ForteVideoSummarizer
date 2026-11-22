"""Unit tests for captions.py. No network: the library client is faked."""

from dataclasses import dataclass, field

import pytest
import youtube_transcript_api as yta

from app.pipeline import captions
from app.pipeline.captions import fetch_caption_track, fetch_captions, pick_track
from app.pipeline.errors import NoCaptions, PipelineError, VideoUnavailable, YouTubeBlocked
from app.pipeline.models import Segment

VID = "dQw4w9WgXcQ"


@dataclass
class FakeSnippet:
    text: str
    start: float
    duration: float


@dataclass
class FakeTranscript:
    language_code: str
    is_generated: bool
    snippets: list = field(default_factory=list)
    fetch_error: Exception | None = None

    def fetch(self):
        if self.fetch_error:
            raise self.fetch_error
        return self.snippets


def manual(code, **kw):
    return FakeTranscript(code, False, **kw)


def auto(code, **kw):
    return FakeTranscript(code, True, **kw)


# --- pick_track ----------------------------------------------------------------


def test_pick_prefers_manual_in_spoken_language():
    tracks = [manual("fr"), manual("en"), auto("en")]
    assert pick_track(tracks) is tracks[1]


def test_pick_matches_manual_regional_variant():
    tracks = [manual("de"), manual("en-GB"), auto("en")]
    assert pick_track(tracks) is tracks[1]


def test_pick_exact_code_beats_regional_variant():
    tracks = [manual("en-GB"), manual("en"), auto("en")]
    assert pick_track(tracks) is tracks[1]


def test_pick_auto_when_no_manual_in_spoken_language():
    # Manual English subs on a Hindi video are a translation; ignore them.
    tracks = [manual("en"), auto("hi")]
    assert pick_track(tracks) is tracks[1]


def test_pick_first_manual_when_no_auto():
    tracks = [manual("es"), manual("en")]
    assert pick_track(tracks) is tracks[0]


def test_pick_only_auto():
    tracks = [auto("ja")]
    assert pick_track(tracks) is tracks[0]


# Auto-dubbed videos have one auto-generated track per dub language; the
# original language (from video metadata) says which one is spoken.
DUBBED = [auto("ar"), auto("de"), auto("en"), auto("fr")]


def test_pick_uses_spoken_language_among_several_auto():
    assert pick_track(DUBBED, spoken="en") is DUBBED[2]


def test_pick_spoken_matches_base_language():
    # yt-dlp reports regional codes like en-US; the tracks say "en".
    assert pick_track(DUBBED, spoken="en-US") is DUBBED[2]


def test_pick_spoken_prefers_manual_in_that_language():
    tracks = [manual("de"), manual("en-GB"), *DUBBED]
    assert pick_track(tracks, spoken="en-US") is tracks[1]


def test_pick_spoken_without_matching_track_falls_back_to_first_auto():
    assert pick_track(DUBBED, spoken="sv") is DUBBED[0]


def test_pick_none_raises_no_captions():
    with pytest.raises(NoCaptions):
        pick_track([])


# --- fetch_captions with a faked client ------------------------------------------


class FakeApi:
    tracks: list = []
    list_error: Exception | None = None

    def list(self, video_id):
        if FakeApi.list_error:
            raise FakeApi.list_error
        return iter(FakeApi.tracks)


@pytest.fixture
def api(monkeypatch):
    FakeApi.tracks = []
    FakeApi.list_error = None
    monkeypatch.setattr(captions, "YouTubeTranscriptApi", FakeApi)
    return FakeApi


def test_fetch_converts_snippets_to_segments(api):
    api.tracks = [
        auto(
            "en",
            snippets=[
                FakeSnippet("hello", 0.0, 2.5),
                FakeSnippet("   ", 2.5, 1.0),  # whitespace-only: skipped
                FakeSnippet("world", 2.5, 0.0),  # zero duration is fine
            ],
        )
    ]
    segments, lang = fetch_captions(VID)
    assert lang == "en"
    assert segments == [
        Segment(start=0.0, end=2.5, text="hello"),
        Segment(start=2.5, end=2.5, text="world"),
    ]


def test_fetch_caption_track_reports_track_type(api):
    api.tracks = [manual("en", snippets=[FakeSnippet("hi", 0, 1)]), auto("en")]
    track = fetch_caption_track(VID)
    assert (track.language, track.is_generated) == ("en", False)


def test_fetch_empty_track_raises_no_captions(api):
    api.tracks = [auto("en", snippets=[FakeSnippet(" ", 0, 1)])]
    with pytest.raises(NoCaptions):
        fetch_captions(VID)


def test_fetch_no_tracks_raises_no_captions(api):
    api.tracks = []
    with pytest.raises(NoCaptions):
        fetch_captions(VID)


class FakeLookup:
    """Stands in for the yt-dlp original-language lookup and records calls."""

    def __init__(self):
        self.result: str | Exception | None = "en-US"
        self.calls: list[str] = []

    def __call__(self, video_id):
        self.calls.append(video_id)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def lookup(monkeypatch):
    fake = FakeLookup()
    monkeypatch.setattr(captions, "video_language", fake)
    return fake


def test_fetch_dubbed_video_uses_original_language(api, lookup):
    api.tracks = [auto(c, snippets=[FakeSnippet(f"in {c}", 0, 1)]) for c in ("ar", "en", "fr")]
    segments, lang = fetch_captions(VID)
    assert (lang, segments[0].text) == ("en", "in en")
    assert lookup.calls == [VID]


def test_fetch_single_auto_track_skips_lookup(api, lookup):
    api.tracks = [manual("fr"), auto("en", snippets=[FakeSnippet("hi", 0, 1)])]
    assert fetch_captions(VID)[1] == "en"
    assert lookup.calls == []


def test_fetch_dubbed_lookup_blocked_raises(api, lookup):
    lookup.result = YouTubeBlocked("blocked")
    api.tracks = [auto("ar"), auto("en")]
    with pytest.raises(YouTubeBlocked):
        fetch_captions(VID)


def test_fetch_dubbed_unknown_language_uses_first_auto(api, lookup):
    lookup.result = None
    api.tracks = [auto("ar", snippets=[FakeSnippet("x", 0, 1)]), auto("en")]
    assert fetch_captions(VID)[1] == "ar"


@pytest.mark.parametrize(
    "lib_error, expected",
    [
        (yta.TranscriptsDisabled(VID), NoCaptions),
        (yta.NoTranscriptFound(VID, ["en"], None), NoCaptions),
        (yta.RequestBlocked(VID), YouTubeBlocked),
        (yta.IpBlocked(VID), YouTubeBlocked),
        (yta.VideoUnavailable(VID), VideoUnavailable),
        (yta.InvalidVideoId(VID), VideoUnavailable),
        (yta.AgeRestricted(VID), VideoUnavailable),
        (yta.VideoUnplayable(VID, "Private video", []), VideoUnavailable),
        (yta.PoTokenRequired(VID), PipelineError),
        (yta.YouTubeDataUnparsable(VID), PipelineError),
    ],
)
@pytest.mark.parametrize("stage", ["list", "fetch"])
def test_library_errors_are_mapped(api, lib_error, expected, stage):
    if stage == "list":
        api.list_error = lib_error
    else:
        api.tracks = [auto("en", fetch_error=lib_error)]
    with pytest.raises(expected) as exc:
        fetch_captions(VID)
    assert exc.value.__cause__ is lib_error
    assert VID in str(exc.value)


def test_blocked_is_not_no_captions(api):
    # A block must never look like "no captions", or the caller would fall back.
    api.list_error = yta.IpBlocked(VID)
    with pytest.raises(PipelineError) as exc:
        fetch_captions(VID)
    assert not isinstance(exc.value, NoCaptions)
