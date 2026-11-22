"""Unit tests for transcript.py. Captions, yt-dlp and STT are all faked."""

from pathlib import Path

import pytest

from app.pipeline import cache, transcript
from app.pipeline.errors import CaptionsRequired, NoCaptions, VideoUnavailable, YouTubeBlocked
from app.pipeline.models import Segment
from app.pipeline.transcript import get_transcript

VID = "dQw4w9WgXcQ"
CAPTION_SEGS = [Segment(start=0, end=2, text="from captions")]
STT_SEGS = [Segment(start=0, end=3, text="from whisper")]


class Fakes:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.captions_result = (CAPTION_SEGS, "en")
        self.captions_error = None
        self.stt_result = (STT_SEGS, "de")
        self.calls = []
        self.audio_dir = None

    def fetch_captions(self, video_id):
        self.calls.append("captions")
        if self.captions_error:
            raise self.captions_error
        return self.captions_result

    def download_audio(self, video_id):
        self.calls.append("download")
        self.audio_dir = self.tmp_path / "dl"
        self.audio_dir.mkdir()
        path = self.audio_dir / f"{video_id}.webm"
        path.write_bytes(b"audio")
        return path

    def transcribe(self, path: Path, openai_client=None):
        self.calls.append("transcribe")
        self.openai_client = openai_client
        assert path.exists()
        return self.stt_result


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    f = Fakes(tmp_path)
    monkeypatch.setattr(transcript, "fetch_captions", f.fetch_captions)
    monkeypatch.setattr(transcript, "download_audio", f.download_audio)
    monkeypatch.setattr(transcript, "transcribe", f.transcribe)
    monkeypatch.setenv("STT_ENGINE", "local")
    return f


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "cache"


def run(cache_dir, **kw):
    stages = []
    result = get_transcript(VID, stages.append, cache_dir=cache_dir, **kw)
    return result, stages


def test_captions_path(fakes, cache_dir):
    result, stages = run(cache_dir)
    assert result == (CAPTION_SEGS, "en", "captions")
    assert stages == ["fetching_captions"]
    assert fakes.calls == ["captions"]


def test_captions_only_never_runs_stt(fakes, cache_dir):
    fakes.captions_error = NoCaptions("none")
    with pytest.raises(CaptionsRequired):
        run(cache_dir, allow_stt=False)
    assert fakes.calls == ["captions"]


def test_captions_only_still_uses_a_cached_stt_transcript(fakes, cache_dir):
    cache.save_transcript(VID, STT_SEGS, "de", "stt-local", cache_dir=cache_dir)
    result, _ = run(cache_dir, allow_stt=False)
    assert result == (STT_SEGS, "de", "stt-local")
    assert fakes.calls == []


def test_no_captions_falls_back_to_stt(fakes, cache_dir):
    fakes.captions_error = NoCaptions("none")
    result, stages = run(cache_dir)
    assert result == (STT_SEGS, "de", "stt-local")
    assert stages == ["fetching_captions", "downloading_audio", "transcribing"]
    assert fakes.calls == ["captions", "download", "transcribe"]
    assert not fakes.audio_dir.exists()  # temp dir cleaned up


def test_openai_client_reaches_stt(fakes, cache_dir):
    fakes.captions_error = NoCaptions("none")
    run(cache_dir, openai_client="user-client")
    assert fakes.openai_client == "user-client"


def test_stt_source_names_engine(fakes, cache_dir, monkeypatch):
    monkeypatch.setenv("STT_ENGINE", "openai")
    fakes.captions_error = NoCaptions("none")
    (_, _, source), _ = run(cache_dir)
    assert source == "stt-openai"


def test_temp_dir_cleaned_when_transcription_fails(fakes, cache_dir, monkeypatch):
    fakes.captions_error = NoCaptions("none")

    def boom(path, openai_client=None):
        raise RuntimeError("model crashed")

    monkeypatch.setattr(transcript, "transcribe", boom)
    with pytest.raises(RuntimeError):
        run(cache_dir)
    assert not fakes.audio_dir.exists()


def test_empty_stt_result_raises_no_captions(fakes, cache_dir):
    fakes.captions_error = NoCaptions("none")
    fakes.stt_result = ([], "en")
    with pytest.raises(NoCaptions, match="no speech"):
        run(cache_dir)
    assert cache.load_transcript(VID, cache_dir=cache_dir) is None


@pytest.mark.parametrize("error", [YouTubeBlocked("blocked"), VideoUnavailable("gone")])
def test_block_and_unavailable_do_not_fall_back(fakes, cache_dir, error):
    fakes.captions_error = error
    with pytest.raises(type(error)):
        run(cache_dir)
    assert fakes.calls == ["captions"]


def test_result_is_cached_and_reused(fakes, cache_dir):
    first, _ = run(cache_dir)
    fakes.calls.clear()
    second, stages = run(cache_dir)
    assert second == first
    assert stages == []
    assert fakes.calls == []


def test_use_cache_false_bypasses_and_overwrites(fakes, cache_dir):
    run(cache_dir)
    fakes.captions_error = NoCaptions("none")
    result, _ = run(cache_dir, use_cache=False)
    assert result[2] == "stt-local"
    assert cache.load_transcript(VID, cache_dir=cache_dir)[2] == "stt-local"


def test_on_stage_optional(fakes, cache_dir):
    assert get_transcript(VID, cache_dir=cache_dir)[2] == "captions"
