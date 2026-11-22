"""Unit tests for tts.py. The Kokoro model is faked; nothing is downloaded."""

import io
import wave

import numpy as np
import pytest

from app.pipeline import tts
from app.pipeline.errors import PipelineError
from app.pipeline.tts import TTSRequestError, default_voice, synthesize, voice_catalog


class FakeEngine:
    def __init__(self):
        self.calls = []

    def speak(self, text, lang, voice):
        self.calls.append((text, lang, voice))
        return np.array([0.0, 0.5, -0.5, 2.0], dtype=np.float32), 24000


@pytest.fixture
def engine():
    return FakeEngine()


def run(engine, tmp_path, text="Hello there.", lang="en", voice=None):
    return synthesize(text, lang, voice, engine=engine, cache_dir=tmp_path)


def test_catalog_lists_supported_languages_with_default_first():
    cat = voice_catalog()
    assert set(cat) == {"en", "es", "fr", "hi", "it", "pt", "zh"}
    assert cat["en"]["default"] == "af_heart" == cat["en"]["voices"][0]["id"]
    assert {"id", "label", "gender", "accent"} <= set(cat["en"]["voices"][0])
    for lang, entry in cat.items():
        assert entry["default"] == default_voice(lang)
        assert entry["default"] in [v["id"] for v in entry["voices"]]


def test_unsupported_language_is_a_request_error():
    for lang in ("de", "ko", "ar", "ru", "ja"):
        assert not tts.supports(lang)
    with pytest.raises(TTSRequestError, match="isn't available"):
        run(FakeEngine(), None, lang="de")


def test_returns_16bit_mono_wav(engine, tmp_path):
    data = run(engine, tmp_path)
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 24000, 4)
        frames = np.frombuffer(w.readframes(4), dtype="<i2")
    assert frames.tolist() == [0, 16383, -16383, 32767]  # clipped at full scale


def test_default_voice_and_kokoro_language(engine, tmp_path):
    run(engine, tmp_path, lang="zh")
    assert engine.calls == [("Hello there.", "cmn", "zf_xiaobei")]


def test_british_voice_uses_british_english(engine, tmp_path):
    run(engine, tmp_path, voice="bf_emma")
    assert engine.calls[0][1:] == ("en-gb", "bf_emma")


def test_voice_must_belong_to_language(engine, tmp_path):
    with pytest.raises(TTSRequestError, match="voice"):
        run(engine, tmp_path, lang="es", voice="af_heart")
    assert engine.calls == []


@pytest.mark.parametrize("text", ["", "   ", "x" * (tts.MAX_CHARS + 1)])
def test_bad_text_is_a_request_error(engine, tmp_path, text):
    with pytest.raises(TTSRequestError):
        run(engine, tmp_path, text=text)


def test_cached_audio_is_reused(engine, tmp_path):
    first = run(engine, tmp_path)
    second = run(engine, tmp_path, text="  Hello there.  ")  # same text after trimming
    assert first == second
    assert len(engine.calls) == 1
    run(engine, tmp_path, voice="af_bella")  # another voice is another clip
    assert len(engine.calls) == 2


def test_engine_failure_is_a_pipeline_error(tmp_path):
    class Broken:
        def speak(self, *a):
            raise RuntimeError("onnx exploded")

    with pytest.raises(PipelineError, match="Speech generation failed") as exc:
        run(Broken(), tmp_path)
    assert not isinstance(exc.value, TTSRequestError)
