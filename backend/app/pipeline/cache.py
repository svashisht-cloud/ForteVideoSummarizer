"""JSON file cache: transcripts by video_id, summaries by (video_id, lang, model)."""

import json
import logging
import os
import re
import tempfile
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.pipeline.models import Segment, Summary

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache"


class _CachedSummary(BaseModel):
    model: str
    prompt_version: int
    summary: Summary


class _CachedTranscript(BaseModel):
    segments: list[Segment]
    language: str
    source: str


def _write(path: Path, data: str | bytes) -> None:
    """Atomic write: readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def _read[T: BaseModel](path: Path, model: type[T]) -> T | None:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValidationError, json.JSONDecodeError) as e:
        log.warning("ignoring unreadable cache file %s: %s", path, e)
        return None


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _summary_path(video_id: str, lang: str, model: str, cache_dir: Path) -> Path:
    return cache_dir / "summaries" / f"{_safe(video_id)}.{_safe(lang)}.{_safe(model)}.json"


def _transcript_path(video_id: str, cache_dir: Path) -> Path:
    return cache_dir / "transcripts" / f"{video_id}.json"


def load_summary(
    video_id: str, lang: str, model: str, prompt_version: int, cache_dir: Path = CACHE_DIR
) -> Summary | None:
    """The cached summary, or None if missing, unreadable, or made by a
    different model or prompt version (the caller then regenerates and
    overwrites it)."""
    path = _summary_path(video_id, lang, model, cache_dir)
    cached = _read(path, _CachedSummary)
    if cached is None:
        return None
    if (cached.model, cached.prompt_version) != (model, prompt_version):
        log.info(
            "cached summary %s is stale (model %s v%d, want %s v%d)",
            path.name, cached.model, cached.prompt_version, model, prompt_version,
        )  # fmt: skip
        return None
    return cached.summary


def save_summary(
    video_id: str,
    lang: str,
    summary: Summary,
    model: str,
    prompt_version: int,
    cache_dir: Path = CACHE_DIR,
) -> None:
    data = _CachedSummary(model=model, prompt_version=prompt_version, summary=summary)
    _write(_summary_path(video_id, lang, model, cache_dir), data.model_dump_json(indent=1))


def load_transcript(video_id: str, cache_dir: Path = CACHE_DIR) -> tuple[list[Segment], str, str] | None:
    """Return (segments, language, source) or None."""
    cached = _read(_transcript_path(video_id, cache_dir), _CachedTranscript)
    return (cached.segments, cached.language, cached.source) if cached else None


def save_transcript(
    video_id: str, segments: list[Segment], language: str, source: str, cache_dir: Path = CACHE_DIR
) -> None:
    data = _CachedTranscript(segments=segments, language=language, source=source)
    _write(_transcript_path(video_id, cache_dir), data.model_dump_json())


def _audio_path(key: str, cache_dir: Path) -> Path:
    return cache_dir / "audio" / f"{_safe(key)}.wav"


def load_audio(key: str, cache_dir: Path = CACHE_DIR) -> bytes | None:
    """Cached speech audio (WAV bytes) for a key made by tts.py, or None."""
    try:
        return _audio_path(key, cache_dir).read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        log.warning("ignoring unreadable audio cache file for %s: %s", key, e)
        return None


def save_audio(key: str, data: bytes, cache_dir: Path = CACHE_DIR) -> None:
    _write(_audio_path(key, cache_dir), data)
