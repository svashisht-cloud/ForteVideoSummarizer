"""Fetch YouTube captions with youtube-transcript-api (v1.x instance API)."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from youtube_transcript_api import (
    AgeRestricted,
    CouldNotRetrieveTranscript,
    InvalidVideoId,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnplayable,
    YouTubeTranscriptApi,
)
from youtube_transcript_api import VideoUnavailable as LibVideoUnavailable

from app.pipeline.errors import NoCaptions, PipelineError, VideoUnavailable, YouTubeBlocked
from app.pipeline.models import Segment
from app.pipeline.stt import video_language

log = logging.getLogger(__name__)


class _Track(Protocol):
    language_code: str
    is_generated: bool

    def fetch(self): ...


@dataclass
class CaptionTrack:
    segments: list[Segment]
    language: str
    is_generated: bool


def _base_lang(code: str) -> str:
    return code.split("-")[0].lower()


def pick_track[T: _Track](tracks: Iterable[T], spoken: str | None = None) -> T:
    """Choose the caption track to use.

    The auto-generated track's language is the spoken language. An auto-dubbed
    video has one auto-generated track per dub language, so the caller passes
    `spoken` (the original language from video metadata) to say which one.
    Prefer a human-made track in the spoken language (exact code first, then a
    regional variant like en-GB for en), else the auto-generated track. With no
    auto-generated track, use the first human-made one. Never translate.
    """
    tracks = list(tracks)
    manual = [t for t in tracks if not t.is_generated]
    generated = [t for t in tracks if t.is_generated]

    if generated:
        chosen = generated[0]
        if spoken:
            match = [t for t in generated if t.language_code == spoken] or [
                t for t in generated if _base_lang(t.language_code) == _base_lang(spoken)
            ]
            if match:
                chosen = match[0]
            else:
                log.warning(
                    "no auto-generated track in original language %r; using %r",
                    spoken, chosen.language_code,
                )  # fmt: skip
        lang = chosen.language_code
        for t in manual:
            if t.language_code == lang:
                return t
        for t in manual:
            if _base_lang(t.language_code) == _base_lang(lang):
                return t
        return chosen
    if manual:
        return manual[0]
    raise NoCaptions("video has no caption tracks")


def _map_error(video_id: str, e: CouldNotRetrieveTranscript) -> PipelineError:
    if isinstance(e, (TranscriptsDisabled, NoTranscriptFound)):
        return NoCaptions(f"video {video_id} has no captions")
    if isinstance(e, RequestBlocked):  # includes IpBlocked
        return YouTubeBlocked(
            f"YouTube blocked the caption request for {video_id} "
            "(bot detection or IP ban); try again later or use a proxy"
        )
    if isinstance(e, AgeRestricted):
        return VideoUnavailable(f"video {video_id} is age-restricted")
    if isinstance(e, VideoUnplayable):
        reason = e.reason or "unplayable"
        return VideoUnavailable(f"video {video_id} is unavailable: {reason}")
    if isinstance(e, (LibVideoUnavailable, InvalidVideoId)):
        return VideoUnavailable(f"video {video_id} is unavailable or does not exist")
    return PipelineError(
        f"could not fetch captions for {video_id}: {type(e).__name__}"
    )


def fetch_caption_track(video_id: str) -> CaptionTrack:
    """Fetch the chosen caption track, with its language and track type."""
    try:
        tracks = list(YouTubeTranscriptApi().list(video_id))
        spoken = None
        if sum(t.is_generated for t in tracks) > 1:
            # Auto-dubbed: the track list can't tell which language is original.
            spoken = video_language(video_id)
        track = pick_track(tracks, spoken)
        snippets = track.fetch()
    except CouldNotRetrieveTranscript as e:
        raise _map_error(video_id, e) from e
    except NoCaptions as e:
        raise NoCaptions(f"video {video_id} has no captions") from e

    segments = [
        Segment(start=s.start, end=s.start + s.duration, text=s.text)
        for s in snippets
        if s.text.strip()
    ]
    if not segments:
        raise NoCaptions(f"video {video_id} has an empty caption track")
    return CaptionTrack(segments, track.language_code, track.is_generated)


def fetch_captions(video_id: str) -> tuple[list[Segment], str]:
    """Return (segments, language_code) from the video's best caption track."""
    track = fetch_caption_track(video_id)
    return track.segments, track.language
