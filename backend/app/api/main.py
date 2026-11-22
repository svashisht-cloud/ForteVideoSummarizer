"""HTTP API: start a summary job, poll its status.

GET  /models                 -> {default, require_user_key, models: [...]}
POST /jobs {url, lang, model?, mode?} (+ optional X-OpenAI-Key header) -> {job_id}
GET  /jobs/{id}              -> {status, stage, progress, result, error}
GET  /tts/voices             -> {lang: {default, voices: [...]}} (languages with a natural voice)
POST /tts {text, lang, voice?} -> audio/wav

Jobs run as background tasks and live in memory. Blocking work (captions,
yt-dlp, speech-to-text) runs in a worker thread so the server stays responsive.

mode "ai" (default): LLM summary in `lang`. mode "free": no LLM, captions only;
key moments are extracted from the captions in the video's own language.

A user's own OpenAI key (X-OpenAI-Key) is used only to build OpenAI clients for
that one job. It is passed to the background task as an argument and never put
on JobStatus (which GET /jobs returns), in a log line, or in the cache.
"""

import asyncio
import logging
import os
import uuid
from typing import Annotated, Literal

import openai
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.pipeline import cache, tts
from app.pipeline.errors import (
    CaptionsRequired,
    InvalidURL,
    NoCaptions,
    PipelineError,
    VideoUnavailable,
    YouTubeBlocked,
)
from app.pipeline.extract import EXTRACT_VERSION, key_moments
from app.pipeline.models import Segment, Summary, VideoMetadata
from app.pipeline.normalize import normalize
from app.pipeline.pricing import available_models, is_known_model
from app.pipeline.stt import video_metadata
from app.pipeline.summarize import PROMPT_VERSION, resolve_model, summarize
from app.pipeline.transcript import get_transcript
from app.pipeline.url import parse_video_id

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
for _noisy in ("httpx", "httpx2", "openai", "huggingface_hub"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger(__name__)

CACHE_DIR = cache.CACHE_DIR
FRONTEND_ORIGINS = ["http://localhost:5173"]

Status = Literal["queued", "running", "done", "error"]
Stage = Literal["fetching_captions", "downloading_audio", "transcribing", "summarizing", "merging"]
Mode = Literal["free", "ai"]
STT_STAGES = ("downloading_audio", "transcribing")
# Cache slot for free summaries: not tied to a summary language or an LLM.
FREE_LANG, FREE_MODEL = "orig", "extractive"


def require_user_key() -> bool:
    """REQUIRE_USER_KEY=true (for deployment): jobs that call OpenAI need the user's own key."""
    return os.environ.get("REQUIRE_USER_KEY", "").strip().lower() in ("1", "true", "yes")


class JobRequest(BaseModel):
    url: str
    lang: str = Field(min_length=1)
    model: str | None = None  # None: the server default (OPENAI_MODEL)
    mode: Mode = "ai"


class JobCreated(BaseModel):
    job_id: str


class Progress(BaseModel):
    done: int
    total: int


class JobResult(BaseModel):
    summary: Summary
    transcript: list[Segment]  # normalized ~30s blocks
    video_id: str
    language: str
    source: str  # captions | stt-local | stt-openai
    summary_cached: bool  # True: the summary came from the cache, so this request made no LLM calls
    mode: Mode = "ai"
    title: str | None = None  # video title, when known (free mode looks it up)


class JobStatus(BaseModel):
    status: Status = "queued"
    stage: Stage | None = None
    progress: Progress | None = None
    result: JobResult | None = None
    error: str | None = None


class SpeechRequest(BaseModel):
    text: str
    lang: str
    voice: str | None = None


class ModelOption(BaseModel):
    id: str
    label: str
    input: float  # USD per 1M tokens
    cached_input: float
    output: float
    cached_is_estimate: bool


class ModelsResponse(BaseModel):
    default: str | None
    require_user_key: bool
    models: list[ModelOption]


JOBS: dict[str, JobStatus] = {}


def error_message(exc: BaseException, stage: str | None) -> str:
    """A message for the UI explaining why a job failed."""
    if isinstance(exc, YouTubeBlocked):
        return "YouTube is blocking requests from this network. Try again later or from a different network."
    if isinstance(exc, VideoUnavailable):
        return f"This video is unavailable (private, removed, age-restricted, or members-only). {exc}"
    if isinstance(exc, CaptionsRequired):
        return "This video has no captions, and Free mode only uses captions. Switch to AI summary to transcribe it."
    if isinstance(exc, NoCaptions):
        return "This video has no captions and no speech could be transcribed from its audio."
    if isinstance(exc, PipelineError):
        if stage in STT_STAGES:
            return f"Speech-to-text failed: {exc}"
        return str(exc)
    return f"Unexpected error: {type(exc).__name__}: {exc}"


def make_openai_clients(api_key: str | None) -> tuple[openai.AsyncOpenAI | None, openai.OpenAI | None]:
    """(async client for summaries, sync client for speech-to-text) for a user's key.
    (None, None) means the pipeline's defaults, which read OPENAI_API_KEY."""
    if not api_key:
        return None, None
    return openai.AsyncOpenAI(api_key=api_key), openai.OpenAI(api_key=api_key)


def _default_model() -> str | None:
    try:
        return resolve_model()
    except PipelineError:
        return None


def _pick_model(requested: str | None) -> str:
    """The model for a job. A requested model must be one the picker offers;
    the server default (OPENAI_MODEL) is always allowed."""
    if requested is None or not requested.strip():
        model = _default_model()
        if model is None:
            raise HTTPException(status_code=400, detail="No model given and OPENAI_MODEL isn't set on the server.")
        return model
    model = requested.strip()
    if not is_known_model(model) and model != _default_model():
        offered = ", ".join(m.id for m in available_models())
        raise HTTPException(status_code=400, detail=f"Unknown model {model!r}. Pick one of: {offered}.")
    return model


def _make_result(
    video_id: str,
    segments: list[Segment],
    language: str,
    source: str,
    summary: Summary,
    summary_cached: bool,
    mode: Mode = "ai",
) -> JobResult:
    meta = cache.load_metadata(video_id, cache_dir=CACHE_DIR)  # local file only, never the network
    return JobResult(
        summary=summary,
        transcript=normalize(segments),
        video_id=video_id,
        language=language,
        source=source,
        summary_cached=summary_cached,
        mode=mode,
        title=meta.title if meta else None,
    )


def _summary_slot(mode: Mode, lang: str, model: str) -> tuple[str, str, int]:
    """(lang, model, version) the summary is cached under."""
    return (FREE_LANG, FREE_MODEL, EXTRACT_VERSION) if mode == "free" else (lang, model, PROMPT_VERSION)


def _cached_result(video_id: str, lang: str, model: str, mode: Mode = "ai") -> JobResult | None:
    """The full result if both the transcript and an up-to-date summary are cached."""
    transcript = cache.load_transcript(video_id, cache_dir=CACHE_DIR)
    if transcript is None:
        return None
    slot_lang, slot_model, version = _summary_slot(mode, lang, model)
    summary = cache.load_summary(video_id, slot_lang, slot_model, version, cache_dir=CACHE_DIR)
    if summary is None:
        return None
    segments, language, source = transcript
    return _make_result(video_id, segments, language, source, summary, summary_cached=True, mode=mode)


def _metadata(video_id: str) -> VideoMetadata:
    """Title and chapters, cached. Best effort: on any failure there are just no chapters."""
    meta = cache.load_metadata(video_id, cache_dir=CACHE_DIR)
    if meta is not None:
        return meta
    try:
        meta = video_metadata(video_id)
    except Exception as e:
        log.warning("no metadata for %s: %s: %s", video_id, type(e).__name__, e)
        return VideoMetadata()
    cache.save_metadata(video_id, meta, cache_dir=CACHE_DIR)
    return meta


async def run_free_job(job: JobStatus, video_id: str) -> None:
    """Free mode: captions only, no LLM. Key moments are picked with TextRank (extract.py)."""
    job.status = "running"

    def on_stage(stage: str) -> None:
        job.stage = stage

    try:
        segments, language, source = await asyncio.to_thread(
            get_transcript, video_id, on_stage, cache_dir=CACHE_DIR, allow_stt=False
        )
        job.stage = "summarizing"
        meta = await asyncio.to_thread(_metadata, video_id)
        summary = key_moments(normalize(segments), language, meta.chapters)
        await asyncio.to_thread(
            cache.save_summary, video_id, FREE_LANG, summary, FREE_MODEL, EXTRACT_VERSION, cache_dir=CACHE_DIR
        )
        job.result = _make_result(video_id, segments, language, source, summary, summary_cached=False, mode="free")
        job.status = "done"
    except Exception as e:
        if not isinstance(e, PipelineError):
            log.exception("free job for %s failed unexpectedly", video_id)
        else:
            log.warning("free job for %s failed at %s: %s: %s", video_id, job.stage, type(e).__name__, e)
        job.error = error_message(e, job.stage)
        job.status = "error"


async def run_job(job: JobStatus, video_id: str, lang: str, model: str, api_key: str | None = None) -> None:
    job.status = "running"

    def on_stage(stage: str) -> None:
        job.stage = stage  # called from the worker thread; a plain attribute write

    def on_progress(stage: str, done: int, total: int) -> None:
        job.stage = stage
        job.progress = Progress(done=done, total=total)

    async_client, sync_client = make_openai_clients(api_key)
    try:
        segments, language, source = await asyncio.to_thread(
            get_transcript, video_id, on_stage, cache_dir=CACHE_DIR, openai_client=sync_client
        )
        summary = await asyncio.to_thread(
            cache.load_summary, video_id, lang, model, PROMPT_VERSION, cache_dir=CACHE_DIR
        )
        summary_cached = summary is not None
        if summary is None:
            job.stage = "summarizing"
            summary = await summarize(segments, lang, on_progress, model=model, client=async_client)
            await asyncio.to_thread(
                cache.save_summary, video_id, lang, summary, model, PROMPT_VERSION, cache_dir=CACHE_DIR
            )
        job.result = _make_result(video_id, segments, language, source, summary, summary_cached)
        job.status = "done"
    except Exception as e:
        if not isinstance(e, PipelineError):
            log.exception("job for %s (%s, %s) failed unexpectedly", video_id, lang, model)
        else:
            log.warning(
                "job for %s (%s, %s) failed at %s: %s: %s", video_id, lang, model, job.stage, type(e).__name__, e
            )  # fmt: skip
        job.error = error_message(e, job.stage)
        job.status = "error"
    finally:
        if async_client is not None:
            await async_client.close()
        if sync_client is not None:
            sync_client.close()


app = FastAPI(title="YouTube Summarizer")
app.add_middleware(
    CORSMiddleware, allow_origins=FRONTEND_ORIGINS, allow_methods=["*"], allow_headers=["*"]
)


@app.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    return ModelsResponse(
        default=_default_model(),
        require_user_key=require_user_key(),
        models=[ModelOption(**vars(m)) for m in available_models()],
    )


@app.post("/jobs", response_model=JobCreated)
async def create_job(
    req: JobRequest,
    background_tasks: BackgroundTasks,
    x_openai_key: Annotated[str | None, Header()] = None,
) -> JobCreated:
    try:
        video_id = parse_video_id(req.url)
    except InvalidURL as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    lang = req.lang.strip()
    if not lang:
        raise HTTPException(status_code=400, detail="lang must not be empty")
    job_id = uuid.uuid4().hex

    if req.mode == "free":  # no model, no key, no LLM
        cached = await asyncio.to_thread(_cached_result, video_id, lang, FREE_MODEL, "free")
        job = JOBS[job_id] = JobStatus()
        if cached is not None:
            job.result, job.status = cached, "done"
        else:
            background_tasks.add_task(run_free_job, job, video_id)
        return JobCreated(job_id=job_id)

    model = _pick_model(req.model)
    api_key = (x_openai_key or "").strip() or None

    cached = await asyncio.to_thread(_cached_result, video_id, lang, model)
    if cached is None and api_key is None and require_user_key():
        raise HTTPException(status_code=400, detail="This server needs your own OpenAI API key to summarize new videos.")

    job = JOBS[job_id] = JobStatus()
    if cached is not None:
        job.result = cached
        job.status = "done"
    else:
        background_tasks.add_task(run_job, job, video_id, lang, model, api_key)
    return JobCreated(job_id=job_id)


@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str) -> JobStatus:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no job with id {job_id!r}")
    return job


@app.get("/tts/voices")
async def tts_voices() -> dict[str, dict]:
    tts.warm()  # the page asks for voices on load: start loading the model now
    return tts.voice_catalog()


@app.post("/tts", response_class=Response, responses={200: {"content": {"audio/wav": {}}}})
async def speak(req: SpeechRequest) -> Response:
    """One clip of natural speech (Kokoro, local). Cached on disk, so replays are instant."""
    try:
        data = await asyncio.to_thread(tts.synthesize, req.text, req.lang, req.voice)
    except tts.TTSRequestError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PipelineError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return Response(content=data, media_type="audio/wav", headers={"Cache-Control": "private, max-age=86400"})
