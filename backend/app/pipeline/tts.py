"""Text-to-speech with Kokoro-82M (Apache 2.0), run locally via kokoro-onnx.

Text is turned into phonemes with misaki for English and Chinese (the phoneme
set Kokoro was trained on; espeak's output sounds noticeably more robotic) and
with espeak for the other languages. Audio is returned as 24 kHz mono 16-bit
WAV and cached in .cache/audio, keyed by model, voice, language and text.

Languages Kokoro can't speak well (German, Korean, Arabic, Russian, and
Japanese, whose kanji espeak can't read) aren't offered; the frontend falls
back to the browser's voice for those.
"""

import hashlib
import io
import logging
import threading
import urllib.request
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

from app.pipeline import cache
from app.pipeline.errors import PipelineError

log = logging.getLogger(__name__)

MODEL_VERSION = "kokoro-v1.0"
G2P_VERSION = "misaki-0.9"  # part of the cache key: phonemes change the audio
MODEL_DIR = cache.CACHE_DIR / "models" / "kokoro"
MODEL_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}
MAX_CHARS = 1500  # one summary point or the TL;DR, with plenty of room


class TTSRequestError(PipelineError):
    """The request can't be served: unsupported language or voice, or bad text."""


@dataclass(frozen=True)
class Voice:
    id: str
    label: str
    gender: Literal["female", "male"]
    accent: str | None = None


@dataclass(frozen=True)
class Language:
    kokoro_lang: str
    voices: tuple[Voice, ...]  # the first is the default


F, M = "female", "male"
# A shortlist of Kokoro's better voices per language (best first), not all 54.
LANGUAGES: dict[str, Language] = {
    "en": Language(
        "en-us",
        (
            Voice("af_heart", "Heart", F, "US"),
            Voice("af_bella", "Bella", F, "US"),
            Voice("af_nicole", "Nicole", F, "US"),
            Voice("am_michael", "Michael", M, "US"),
            Voice("am_fenrir", "Fenrir", M, "US"),
            Voice("bf_emma", "Emma", F, "UK"),
            Voice("bm_george", "George", M, "UK"),
        ),
    ),
    "es": Language("es", (Voice("ef_dora", "Dora", F), Voice("em_alex", "Alex", M))),
    "fr": Language("fr-fr", (Voice("ff_siwis", "Siwis", F),)),
    "hi": Language(
        "hi",
        (Voice("hf_alpha", "Alpha", F), Voice("hf_beta", "Beta", F), Voice("hm_omega", "Omega", M), Voice("hm_psi", "Psi", M)),
    ),
    "it": Language("it", (Voice("if_sara", "Sara", F), Voice("im_nicola", "Nicola", M))),
    "pt": Language("pt-br", (Voice("pf_dora", "Dora", F), Voice("pm_alex", "Alex", M))),
    "zh": Language(
        "cmn",
        (
            Voice("zf_xiaobei", "Xiaobei", F),
            Voice("zf_xiaoni", "Xiaoni", F),
            Voice("zm_yunjian", "Yunjian", M),
            Voice("zm_yunxi", "Yunxi", M),
        ),
    ),
}


def supports(lang: str) -> bool:
    return lang in LANGUAGES


def default_voice(lang: str) -> str:
    return LANGUAGES[lang].voices[0].id


def voice_catalog() -> dict[str, dict]:
    """{lang: {default, voices: [{id, label, gender, accent}]}} for the UI."""
    return {
        code: {"default": lang.voices[0].id, "voices": [asdict(v) for v in lang.voices]}
        for code, lang in LANGUAGES.items()
    }


class Engine(Protocol):
    def speak(self, text: str, lang: str, voice: str) -> tuple[np.ndarray, int]:
        """Audio samples (float32, -1..1) and sample rate. `lang` is the Kokoro language."""
        ...


def _download_model(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, url in MODEL_FILES.items():
        path = model_dir / name
        if path.exists():
            continue
        log.info("downloading Kokoro model file %s (one time)…", name)
        part = path.with_suffix(path.suffix + ".part")
        try:
            urllib.request.urlretrieve(url, part)
            part.replace(path)
        except OSError as e:
            part.unlink(missing_ok=True)
            raise PipelineError(f"couldn't download the Kokoro voice model ({name}): {e}") from e


class KokoroEngine:
    """The real engine. Load it once; it isn't safe to call concurrently."""

    def __init__(self, model_dir: Path = MODEL_DIR):
        _download_model(model_dir)
        from kokoro_onnx import Kokoro  # heavy imports, only when speech is first used
        from misaki import en, zh
        from misaki.espeak import EspeakFallback

        self._kokoro = Kokoro(str(model_dir / "kokoro-v1.0.onnx"), str(model_dir / "voices-v1.0.bin"))
        self._g2p = {
            "en-us": en.G2P(trf=False, british=False, fallback=EspeakFallback(british=False)),
            "en-gb": en.G2P(trf=False, british=True, fallback=EspeakFallback(british=True)),
            "cmn": zh.ZHG2P(),
        }

    def speak(self, text: str, lang: str, voice: str) -> tuple[np.ndarray, int]:
        g2p = self._g2p.get(lang)
        if g2p is None:  # espeak inside kokoro-onnx
            return self._kokoro.create(text, voice=voice, lang=lang)
        phonemes = g2p(text)[0]
        return self._kokoro.create(phonemes, voice=voice, lang=lang, is_phonemes=True)


_engine: Engine | None = None
_lock = threading.Lock()  # one synthesis at a time; also guards loading


_warming = False


def warm() -> None:
    """Load the model in a background thread (idempotent), so the first Listen
    doesn't wait for it. Failures are logged; synthesize() reports them properly."""
    global _warming
    if _engine is not None or _warming:
        return
    _warming = True

    def load() -> None:
        global _engine
        try:
            with _lock:
                if _engine is None:
                    _engine = KokoroEngine()
            log.info("Kokoro voice model loaded")
        except Exception as e:
            log.warning("couldn't preload the Kokoro voice model: %s", e)

    threading.Thread(target=load, name="kokoro-warm", daemon=True).start()


def _wav(samples: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _cache_key(text: str, kokoro_lang: str, voice: str) -> str:
    raw = f"{MODEL_VERSION}|{G2P_VERSION}|{voice}|{kokoro_lang}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def synthesize(
    text: str,
    lang: str,
    voice: str | None = None,
    *,
    engine: Engine | None = None,
    cache_dir: Path | None = None,
) -> bytes:
    """Speak `text` (in summary language `lang`) and return WAV bytes. Blocking:
    call it from a worker thread in async code."""
    if lang not in LANGUAGES:
        raise TTSRequestError(f"Natural voice isn't available for {lang!r}.")
    language = LANGUAGES[lang]
    voice = voice or language.voices[0].id
    if voice not in {v.id for v in language.voices}:
        raise TTSRequestError(f"Unknown voice {voice!r} for {lang!r}.")
    text = text.strip()
    if not text:
        raise TTSRequestError("No text to speak.")
    if len(text) > MAX_CHARS:
        raise TTSRequestError(f"Text is too long to speak at once ({len(text)} characters; max {MAX_CHARS}).")

    kokoro_lang = "en-gb" if voice.startswith("b") else language.kokoro_lang
    cache_dir = cache_dir or cache.CACHE_DIR
    key = _cache_key(text, kokoro_lang, voice)
    cached = cache.load_audio(key, cache_dir=cache_dir)
    if cached is not None:
        return cached

    global _engine
    with _lock:
        try:
            if engine is None:
                if _engine is None:
                    _engine = KokoroEngine()
                engine = _engine
            samples, rate = engine.speak(text, kokoro_lang, voice)
        except PipelineError:
            raise
        except Exception as e:
            log.exception("speech generation failed (%s, %s)", lang, voice)
            raise PipelineError(f"Speech generation failed: {type(e).__name__}: {e}") from e
    data = _wav(samples, rate)
    cache.save_audio(key, data, cache_dir=cache_dir)
    return data
