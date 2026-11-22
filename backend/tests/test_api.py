"""API tests with FastAPI's TestClient. The pipeline is faked; the cache uses tmp_path."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.pipeline import cache
from app.pipeline.errors import NoCaptions, PipelineError, VideoUnavailable, YouTubeBlocked
from app.pipeline.models import Point, Section, Segment, Summary, Usage
from app.pipeline.summarize import PROMPT_VERSION

VID = "dQw4w9WgXcQ"
URL = f"https://www.youtube.com/watch?v={VID}"
MODEL = "test-model"
SEGMENTS = [
    Segment(start=0, end=10, text="hello"),
    Segment(start=10, end=40, text="world"),
    Segment(start=40, end=50, text="again"),
]
SUMMARY = Summary(
    tldr="A greeting.",
    sections=[Section(title="Intro", start=0, end=50, points=[Point(t=0, text="Says hello.")])],
    usage=Usage(model=MODEL, calls=1, input_tokens=1200, cached_input_tokens=0, output_tokens=300, cost_usd=0.0027),
)


class Fakes:
    def __init__(self):
        self.calls: list[str] = []
        self.transcript_error: Exception | None = None
        self.summarize_error: Exception | None = None
        self.stages = ["fetching_captions"]
        self.seen_progress: list[tuple] = []

    def get_transcript(self, video_id, on_stage=None, **kwargs):
        self.calls.append("transcript")
        self.transcript_kwargs = kwargs
        for s in self.stages:
            on_stage(s)
        if self.transcript_error:
            raise self.transcript_error
        return SEGMENTS, "en", "captions"

    async def summarize(self, segments, target_lang, on_progress=None, **kwargs):
        self.calls.append(f"summarize:{target_lang}")
        self.summarize_kwargs = kwargs
        on_progress("summarizing", 0, 2)
        on_progress("summarizing", 2, 2)
        on_progress("merging", 0, 1)
        if self.summarize_error:
            raise self.summarize_error
        return SUMMARY


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    f = Fakes()
    monkeypatch.setattr(main, "get_transcript", f.get_transcript)
    monkeypatch.setattr(main, "summarize", f.summarize)
    monkeypatch.setattr(main, "resolve_model", lambda: MODEL)
    monkeypatch.setattr(main, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(main, "JOBS", {})
    monkeypatch.delenv("REQUIRE_USER_KEY", raising=False)
    return f


@pytest.fixture
def client():
    return TestClient(main.app)


def start(client, url=URL, lang="en"):
    r = client.post("/jobs", json={"url": url, "lang": lang})
    assert r.status_code == 200, r.text
    return r.json()["job_id"]


def get(client, job_id):
    r = client.get(f"/jobs/{job_id}")
    assert r.status_code == 200, r.text
    return r.json()


def test_bad_url_is_400(fakes, client):
    r = client.post("/jobs", json={"url": "https://vimeo.com/123", "lang": "en"})
    assert r.status_code == 400
    assert "not a YouTube URL" in r.json()["detail"]
    assert fakes.calls == []


def test_blank_lang_is_400(fakes, client):
    r = client.post("/jobs", json={"url": URL, "lang": "  "})
    assert r.status_code == 400


def test_missing_lang_is_422(fakes, client):
    assert client.post("/jobs", json={"url": URL}).status_code == 422


def test_unknown_job_is_404(fakes, client):
    assert client.get("/jobs/nope").status_code == 404


def test_happy_path(fakes, client):
    job = get(client, start(client, lang="de"))
    assert job["status"] == "done"
    assert job["error"] is None
    assert job["stage"] == "merging"
    assert job["progress"] == {"done": 0, "total": 1}
    result = job["result"]
    assert result["video_id"] == VID
    assert result["language"] == "en"
    assert result["source"] == "captions"
    assert result["summary"] == SUMMARY.model_dump()
    # normalized ~30s blocks, not raw segments
    assert [b["text"] for b in result["transcript"]] == ["hello world", "again"]
    assert result["summary_cached"] is False
    assert fakes.calls == ["transcript", "summarize:de"]


def test_summary_is_cached_after_run(fakes, client, tmp_path):
    start(client)
    assert cache.load_summary(VID, "en", MODEL, PROMPT_VERSION, cache_dir=tmp_path) == SUMMARY


def test_cache_hit_is_done_immediately(fakes, client, tmp_path):
    cache.save_transcript(VID, SEGMENTS, "en", "stt-local", cache_dir=tmp_path)
    cache.save_summary(VID, "en", SUMMARY, MODEL, PROMPT_VERSION, cache_dir=tmp_path)
    job = get(client, start(client))
    assert job["status"] == "done"
    assert job["result"]["source"] == "stt-local"
    assert job["result"]["summary_cached"] is True
    assert job["result"]["summary"] == SUMMARY.model_dump()
    assert fakes.calls == []


def test_stale_summary_cache_runs_summarize(fakes, client, tmp_path):
    cache.save_transcript(VID, SEGMENTS, "en", "captions", cache_dir=tmp_path)
    cache.save_summary(VID, "en", SUMMARY, "other-model", PROMPT_VERSION, cache_dir=tmp_path)
    assert get(client, start(client))["status"] == "done"
    assert "summarize:en" in fakes.calls


@pytest.mark.parametrize(
    ("stages", "error", "expected"),
    [
        (["fetching_captions"], YouTubeBlocked("blocked"), "YouTube is blocking requests from this network"),
        (["fetching_captions"], VideoUnavailable("video x is private"), "This video is unavailable"),
        (
            ["fetching_captions", "downloading_audio", "transcribing"],
            PipelineError("ffmpeg failed"),
            "Speech-to-text failed: ffmpeg failed",
        ),
        (["fetching_captions", "downloading_audio", "transcribing"], NoCaptions("no speech"), "no captions"),
        (["fetching_captions"], RuntimeError("boom"), "Unexpected error: RuntimeError: boom"),
    ],
)
def test_transcript_errors(fakes, client, stages, error, expected):
    fakes.stages = stages
    fakes.transcript_error = error
    job = get(client, start(client))
    assert job["status"] == "error"
    assert expected in job["error"]
    assert job["stage"] == stages[-1]
    assert job["result"] is None


def test_summarize_error(fakes, client):
    fakes.summarize_error = PipelineError("OpenAI request failed for merge: timeout")
    job = get(client, start(client))
    assert job["status"] == "error"
    assert job["stage"] == "merging"
    assert job["error"] == "OpenAI request failed for merge: timeout"


def test_cors_preflight(fakes, client):
    r = client.options(
        "/jobs",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_error_message_stt_only_in_stt_stages():
    assert main.error_message(PipelineError("x"), "summarizing") == "x"
    assert main.error_message(PipelineError("x"), "downloading_audio") == "Speech-to-text failed: x"
    assert main.error_message(YouTubeBlocked("x"), "transcribing").startswith("YouTube is blocking")


def test_summary_cached_when_only_summary_is_cached(fakes, client, tmp_path):
    # Transcript not cached, summary is: the job fetches the transcript but makes no LLM calls.
    cache.save_summary(VID, "en", SUMMARY, MODEL, PROMPT_VERSION, cache_dir=tmp_path)
    result = get(client, start(client))["result"]
    assert result["summary_cached"] is True
    assert result["summary"]["usage"]["cost_usd"] == 0.0027
    assert fakes.calls == ["transcript"]


# --- model picker ---------------------------------------------------------------------


def test_models_endpoint(fakes, client):
    body = client.get("/models").json()
    assert body["default"] == MODEL
    assert body["require_user_key"] is False
    assert [m["id"] for m in body["models"]] == ["gpt-6-luna", "gpt-6.1-terra", "gpt-6.1-sol", "gpt-6-astra"]
    assert body["models"][1] | {} == {
        "id": "gpt-6.1-terra", "label": "GPT-6.1 Terra", "input": 1.0, "cached_input": 0.05, "output": 5.0,
        "cached_is_estimate": False,
    }  # fmt: skip


def test_default_model_used_when_none_given(fakes, client):
    start(client)
    assert fakes.summarize_kwargs["model"] == MODEL


def test_requested_model_is_used(fakes, client):
    r = client.post("/jobs", json={"url": URL, "lang": "en", "model": "gpt-6.1-sol"})
    assert r.status_code == 200
    assert fakes.summarize_kwargs["model"] == "gpt-6.1-sol"


def test_unknown_model_is_400(fakes, client):
    r = client.post("/jobs", json={"url": URL, "lang": "en", "model": "gpt-3"})
    assert r.status_code == 400
    assert "Unknown model" in r.json()["detail"]
    assert fakes.calls == []


def test_summary_cache_is_per_model(fakes, client, tmp_path):
    cache.save_transcript(VID, SEGMENTS, "en", "captions", cache_dir=tmp_path)
    cache.save_summary(VID, "en", SUMMARY, "gpt-6.1-sol", PROMPT_VERSION, cache_dir=tmp_path)
    # Same video and language, another model: not a cache hit.
    r = client.post("/jobs", json={"url": URL, "lang": "en", "model": "gpt-6-luna"})
    assert get(client, r.json()["job_id"])["result"]["summary_cached"] is False
    # The sol summary is still there.
    r = client.post("/jobs", json={"url": URL, "lang": "en", "model": "gpt-6.1-sol"})
    assert get(client, r.json()["job_id"])["result"]["summary_cached"] is True


# --- user's own API key ---------------------------------------------------------------

KEY = "sk-test-user-key-1234"


@pytest.fixture
def clients(monkeypatch):
    """Records the keys clients are built from; returns marker objects instead of real clients."""
    made = []

    class FakeAsync:
        async def close(self):
            pass

    class FakeSync:
        def close(self):
            pass

    def make(api_key):
        made.append(api_key)
        return (FakeAsync(), FakeSync()) if api_key else (None, None)

    monkeypatch.setattr(main, "make_openai_clients", make)
    return made


def test_user_key_builds_clients_for_the_job(fakes, client, clients, caplog):
    with caplog.at_level(logging.DEBUG):
        r = client.post("/jobs", json={"url": URL, "lang": "en"}, headers={"X-OpenAI-Key": f"  {KEY} "})
        job_text = client.get(f"/jobs/{r.json()['job_id']}").text
    assert clients == [KEY]
    assert fakes.summarize_kwargs["client"] is not None
    assert fakes.transcript_kwargs["openai_client"] is not None
    assert KEY not in job_text
    assert KEY not in caplog.text


def test_no_key_uses_server_defaults(fakes, client, clients):
    start(client)
    assert clients == [None]
    assert fakes.summarize_kwargs["client"] is None


def test_key_never_in_error_output(fakes, client, clients, caplog):
    fakes.summarize_error = PipelineError("Your OpenAI API key was rejected. Check that it's correct and active.")
    with caplog.at_level(logging.DEBUG):
        r = client.post("/jobs", json={"url": URL, "lang": "en"}, headers={"X-OpenAI-Key": KEY})
        job = get(client, r.json()["job_id"])
    assert job["error"].startswith("Your OpenAI API key was rejected")
    assert KEY not in str(job)
    assert KEY not in caplog.text


def test_require_user_key(fakes, client, clients, monkeypatch, tmp_path):
    monkeypatch.setenv("REQUIRE_USER_KEY", "true")
    assert client.get("/models").json()["require_user_key"] is True
    r = client.post("/jobs", json={"url": URL, "lang": "en"})
    assert r.status_code == 400
    assert "your own OpenAI API key" in r.json()["detail"]
    assert fakes.calls == []
    # With a key it runs.
    r = client.post("/jobs", json={"url": URL, "lang": "en"}, headers={"X-OpenAI-Key": KEY})
    assert get(client, r.json()["job_id"])["status"] == "done"
    # Cache hits stay free without a key. (The faked get_transcript doesn't write the transcript cache.)
    cache.save_transcript(VID, SEGMENTS, "en", "captions", cache_dir=tmp_path)
    r = client.post("/jobs", json={"url": URL, "lang": "en"})
    assert r.status_code == 200
    assert get(client, r.json()["job_id"])["result"]["summary_cached"] is True


# --- text to speech -------------------------------------------------------------------


def test_tts_voices(client, monkeypatch):
    warmed = []
    monkeypatch.setattr(main.tts, "warm", lambda: warmed.append(True))
    body = client.get("/tts/voices").json()
    assert warmed == [True]
    assert body["en"]["default"] == "af_heart"
    assert "de" not in body


def test_tts_returns_wav(client, monkeypatch):
    calls = []

    def fake(text, lang, voice):
        calls.append((text, lang, voice))
        return b"RIFF-fake-wav"

    monkeypatch.setattr(main.tts, "synthesize", fake)
    r = client.post("/tts", json={"text": "Hello", "lang": "en", "voice": "bf_emma"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content == b"RIFF-fake-wav"
    assert calls == [("Hello", "en", "bf_emma")]


def test_tts_bad_request_is_400(client, monkeypatch):
    def fake(text, lang, voice):
        raise main.tts.TTSRequestError("Natural voice isn't available for 'de'.")

    monkeypatch.setattr(main.tts, "synthesize", fake)
    r = client.post("/tts", json={"text": "Hallo", "lang": "de"})
    assert r.status_code == 400
    assert "isn't available" in r.json()["detail"]


def test_tts_engine_failure_is_503(client, monkeypatch):
    def fake(text, lang, voice):
        raise PipelineError("couldn't download the Kokoro voice model")

    monkeypatch.setattr(main.tts, "synthesize", fake)
    assert client.post("/tts", json={"text": "Hi", "lang": "en"}).status_code == 503
