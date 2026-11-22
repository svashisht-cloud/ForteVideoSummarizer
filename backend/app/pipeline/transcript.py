"""get_transcript: the single entry point for transcripts.

Captions first; speech-to-text only when the video has no captions. A blocked
request (YouTubeBlocked) is re-raised and never falls back, since yt-dlp would
usually be blocked too. Results are cached by video_id.
"""

import shutil
from collections.abc import Callable
from pathlib import Path

from app.pipeline import cache
from app.pipeline.captions import fetch_captions
from app.pipeline.errors import CaptionsRequired, NoCaptions
from app.pipeline.models import Segment
from app.pipeline.stt import download_audio, engine_name, transcribe

StageFn = Callable[[str], None]


def get_transcript(
    video_id: str,
    on_stage: StageFn | None = None,
    *,
    use_cache: bool = True,
    cache_dir: Path = cache.CACHE_DIR,
    openai_client=None,
    allow_stt: bool = True,
) -> tuple[list[Segment], str, str]:
    """Return (segments, language, source); source is captions | stt-local | stt-openai.
    openai_client is used for OpenAI speech-to-text (STT_ENGINE=openai)."""
    if use_cache:
        cached = cache.load_transcript(video_id, cache_dir=cache_dir)
        if cached is not None:
            return cached

    stage = on_stage or (lambda s: None)
    stage("fetching_captions")
    try:
        segments, language = fetch_captions(video_id)
        source = "captions"
    except NoCaptions as e:
        if not allow_stt:
            raise CaptionsRequired(f"video {video_id} has no captions") from e
        source = f"stt-{engine_name()}"
        stage("downloading_audio")
        audio = download_audio(video_id)
        try:
            stage("transcribing")
            segments, language = transcribe(audio, openai_client=openai_client)
        finally:
            shutil.rmtree(audio.parent, ignore_errors=True)
        if not segments:
            raise NoCaptions(f"video {video_id} has no captions and no speech was found in its audio")

    cache.save_transcript(video_id, segments, language, source, cache_dir=cache_dir)
    return segments, language, source
