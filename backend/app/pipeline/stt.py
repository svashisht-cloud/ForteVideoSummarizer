"""Speech-to-text fallback: download audio with yt-dlp, transcribe it locally
(mlx-whisper) or with the OpenAI API. Engine chosen by STT_ENGINE."""

import logging
import math
import os
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import openai
import yt_dlp

from app.pipeline.errors import PipelineError, VideoUnavailable, YouTubeBlocked, openai_error_message
from app.pipeline.models import Segment

log = logging.getLogger(__name__)

ENGINES = ("local", "openai")
LOCAL_MODEL = "mlx-community/whisper-large-v3-turbo"
# gpt-transcribe (the only non-deprecated model) returns text only: it rejects
# verbose_json/srt/vtt, so it has no timestamps. whisper-1 returns segments but
# is scheduled to shut down on 2027-02-26.
DEFAULT_OPENAI_STT_MODEL = "whisper-1"
MAX_UPLOAD_BYTES = 24_000_000  # API limit is 25 MB
# whisper-1 takes ~2.5s per audio minute and can't stream, so a long upload sits
# idle past the ~60s idle timeout on the network path and gets cut. 10-minute
# pieces return in ~25s; they're uploaded concurrently.
MAX_PIECE_SECONDS = 600.0
MAX_CONCURRENT_UPLOADS = 4
SPLIT_MARGIN = 0.9  # pieces cut with -c copy can be a little over their share

# Whisper's language names (and aliases) -> ISO 639-1, from whisper's tokenizer.
# whisper-1's verbose_json reports names like "english".
LANGUAGE_CODES = {
    "afrikaans": "af", "albanian": "sq", "amharic": "am", "arabic": "ar",
    "armenian": "hy", "assamese": "as", "azerbaijani": "az", "bashkir": "ba",
    "basque": "eu", "belarusian": "be", "bengali": "bn", "bosnian": "bs",
    "breton": "br", "bulgarian": "bg", "burmese": "my", "cantonese": "yue",
    "castilian": "es", "catalan": "ca", "chinese": "zh", "croatian": "hr",
    "czech": "cs", "danish": "da", "dutch": "nl", "english": "en", "estonian": "et",
    "faroese": "fo", "finnish": "fi", "flemish": "nl", "french": "fr",
    "galician": "gl", "georgian": "ka", "german": "de", "greek": "el",
    "gujarati": "gu", "haitian": "ht", "haitian creole": "ht", "hausa": "ha",
    "hawaiian": "haw", "hebrew": "he", "hindi": "hi", "hungarian": "hu",
    "icelandic": "is", "indonesian": "id", "italian": "it", "japanese": "ja",
    "javanese": "jw", "kannada": "kn", "kazakh": "kk", "khmer": "km", "korean": "ko",
    "lao": "lo", "latin": "la", "latvian": "lv", "letzeburgesch": "lb",
    "lingala": "ln", "lithuanian": "lt", "luxembourgish": "lb", "macedonian": "mk",
    "malagasy": "mg", "malay": "ms", "malayalam": "ml", "maltese": "mt",
    "mandarin": "zh", "maori": "mi", "marathi": "mr", "moldavian": "ro",
    "moldovan": "ro", "mongolian": "mn", "myanmar": "my", "nepali": "ne",
    "norwegian": "no", "nynorsk": "nn", "occitan": "oc", "panjabi": "pa",
    "pashto": "ps", "persian": "fa", "polish": "pl", "portuguese": "pt",
    "punjabi": "pa", "pushto": "ps", "romanian": "ro", "russian": "ru",
    "sanskrit": "sa", "serbian": "sr", "shona": "sn", "sindhi": "sd", "sinhala": "si",
    "sinhalese": "si", "slovak": "sk", "slovenian": "sl", "somali": "so",
    "spanish": "es", "sundanese": "su", "swahili": "sw", "swedish": "sv",
    "tagalog": "tl", "tajik": "tg", "tamil": "ta", "tatar": "tt", "telugu": "te",
    "thai": "th", "tibetan": "bo", "turkish": "tr", "turkmen": "tk", "ukrainian": "uk",
    "urdu": "ur", "uzbek": "uz", "valencian": "ca", "vietnamese": "vi", "welsh": "cy",
    "yiddish": "yi", "yoruba": "yo",
}  # fmt: skip
_CODES = set(LANGUAGE_CODES.values())


# --- Pure helpers --------------------------------------------------------------


def to_segments(raw: Iterable[Mapping[str, Any]]) -> list[Segment]:
    """Whisper-style {start, end, text} dicts -> Segments. Skips empty text,
    clamps start >= 0 and end >= start."""
    out = []
    for r in raw:
        text = str(r["text"]).strip()
        if not text:
            continue
        start = max(0.0, float(r["start"]))
        out.append(Segment(start=start, end=max(start, float(r["end"])), text=text))
    return out


def offset_segments(segments: list[Segment], offset: float) -> list[Segment]:
    if not offset:
        return segments
    return [Segment(start=s.start + offset, end=s.end + offset, text=s.text) for s in segments]


def plan_pieces(
    duration: float,
    size_bytes: int,
    max_bytes: int = MAX_UPLOAD_BYTES,
    max_seconds: float = MAX_PIECE_SECONDS,
) -> list[tuple[float, float]]:
    """Split [0, duration] into equal (start, length) pieces, each under both the
    upload size limit and the per-request duration cap."""
    by_size = math.ceil(size_bytes / (max_bytes * SPLIT_MARGIN)) if size_bytes >= max_bytes * SPLIT_MARGIN else 1
    by_time = max(1, math.ceil(duration / max_seconds - 1e-9))
    n = max(by_size, by_time)
    if n == 1:
        return [(0.0, float(duration))]
    length = duration / n
    return [(i * length, duration - i * length if i == n - 1 else length) for i in range(n)]


def normalize_language(value: Any) -> str:
    """"english" / "en" / [{"code": "en"}] -> "en". Unknown -> "und"."""
    if isinstance(value, list):
        if not value:
            return "und"
        first = value[0]
        value = first.get("code") if isinstance(first, Mapping) else getattr(first, "code", None)
    if not value:
        return "und"
    v = str(value).strip().lower()
    if v in _CODES:
        return v
    return LANGUAGE_CODES.get(v, "und")


_BLOCKED = ("not a bot", "http error 429", "too many requests")
_UNAVAILABLE = (
    "video unavailable", "private video", "has been removed", "confirm your age",
    "age-restricted", "members-only", "this live event", "premieres in",
)  # fmt: skip


def map_ytdlp_error(video_id: str, msg: str) -> PipelineError:
    m = msg.lower()
    if any(p in m for p in _BLOCKED):
        return YouTubeBlocked(f"YouTube blocked the audio download for {video_id} (bot detection or rate limit)")
    if any(p in m for p in _UNAVAILABLE):
        return VideoUnavailable(f"video {video_id} is unavailable: {msg.removeprefix('ERROR: ').strip()}")
    return PipelineError(f"audio download failed for {video_id}: {msg.removeprefix('ERROR: ').strip()}")


# --- Metadata ------------------------------------------------------------------------


def video_language(video_id: str) -> str | None:
    """The video's original spoken language from YouTube metadata (e.g. "en-US"),
    or None if YouTube doesn't say. Fetches metadata only, no download."""
    opts = {"skip_download": True, "noplaylist": True, "quiet": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except yt_dlp.utils.DownloadError as e:
        raise map_ytdlp_error(video_id, str(e)) from e
    language = (info or {}).get("language")
    return language if isinstance(language, str) and language.strip() else None


# --- Download ------------------------------------------------------------------------


def download_audio(video_id: str) -> Path:
    """Download the best audio-only stream to a new temp dir. The caller removes
    the returned file's parent directory."""
    tmp = Path(tempfile.mkdtemp(prefix=f"yts-{video_id}-"))
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(tmp / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
    except yt_dlp.utils.DownloadError as e:
        raise map_ytdlp_error(video_id, str(e)) from e
    downloads = (info or {}).get("requested_downloads") or []
    if downloads and downloads[0].get("filepath"):
        return Path(downloads[0]["filepath"])
    files = [p for p in tmp.iterdir() if not p.name.endswith(".part")]
    if not files:
        raise PipelineError(f"audio download for {video_id} produced no file")
    return files[0]


# --- Engines -------------------------------------------------------------------------


def engine_name() -> str:
    return os.environ.get("STT_ENGINE", "local").strip().lower() or "local"


def transcribe(audio_path: Path, openai_client=None) -> tuple[list[Segment], str]:
    """Transcribe with the engine named by STT_ENGINE. Returns (segments, ISO language).
    openai_client (e.g. built from a user's own key) is used by the openai engine."""
    engine = engine_name()
    if engine == "local":
        return transcribe_local(audio_path)
    if engine == "openai":
        return transcribe_openai(audio_path, client=openai_client)
    raise PipelineError(f"unknown STT_ENGINE {engine!r}; use one of {', '.join(ENGINES)}")


def transcribe_local(audio_path: Path) -> tuple[list[Segment], str]:
    try:
        import mlx_whisper  # Apple Silicon only; imported lazily
    except ImportError as e:
        raise PipelineError("mlx-whisper isn't installed (needs Apple Silicon macOS); set STT_ENGINE=openai") from e
    result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=LOCAL_MODEL)
    return to_segments(result["segments"]), normalize_language(result.get("language"))


def openai_stt_model() -> str:
    return os.environ.get("OPENAI_STT_MODEL", "").strip() or DEFAULT_OPENAI_STT_MODEL


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    except FileNotFoundError as e:
        raise PipelineError(f"{cmd[0]} not found; install it with `brew install ffmpeg`") from e
    except subprocess.CalledProcessError as e:
        raise PipelineError(f"{cmd[0]} failed: {e.stderr.strip()[-300:]}") from e


def _compress(src: Path, dst: Path) -> None:
    """Mono 16 kHz Opus at 24 kbps: about 11 MB per hour of speech."""
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
          "-c:a", "libopus", "-b:a", "24k", str(dst)])  # fmt: skip


def _probe_duration(path: Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.strip())


def _cut(src: Path, start: float, length: float, dst: Path) -> None:
    _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(src),
          "-c", "copy", str(dst)])  # fmt: skip


def transcribe_openai(
    audio_path: Path,
    *,
    client=None,
    model: str | None = None,
    max_bytes: int = MAX_UPLOAD_BYTES,
    max_seconds: float = MAX_PIECE_SECONDS,
) -> tuple[list[Segment], str]:
    """Compress, split into pieces (upload size limit and per-request duration
    cap), transcribe pieces concurrently, and shift each piece's timestamps by
    its start."""
    model = model or openai_stt_model()
    client = client or openai.OpenAI()
    with tempfile.TemporaryDirectory(prefix="yts-stt-") as work:
        work = Path(work)
        compressed = work / "audio.ogg"
        _compress(audio_path, compressed)
        size = compressed.stat().st_size
        duration = _probe_duration(compressed)
        pieces = plan_pieces(duration, size, max_bytes, max_seconds)
        if len(pieces) == 1:
            uploads = [(0.0, compressed)]
        else:
            log.info("audio is %.1f MB / %.0f min; %d pieces", size / 1e6, duration / 60, len(pieces))
            uploads = []
            for i, (start, length) in enumerate(pieces):
                path = work / f"piece{i:03d}.ogg"
                _cut(compressed, start, length, path)
                uploads.append((start, path))

        with ThreadPoolExecutor(MAX_CONCURRENT_UPLOADS) as pool:
            results = list(pool.map(lambda u: _transcribe_piece(client, model, u[1]), uploads))

        segments: list[Segment] = []
        languages: Counter[str] = Counter()
        for (start, _), (segs, lang) in zip(uploads, results):
            segments += offset_segments(segs, start)
            languages[lang] += len(segs)
    return segments, (languages.most_common(1)[0][0] if languages else "und")


def _transcribe_piece(client, model: str, path: Path) -> tuple[list[Segment], str]:
    try:
        with open(path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model=model, file=f, response_format="verbose_json", timestamp_granularities=["segment"]
            )
    except openai.APIError as e:
        raise PipelineError(openai_error_message(e, model, f"transcription ({model})")) from e
    if resp.segments is None:
        raise PipelineError(f"{model} returned no segment timestamps; set OPENAI_STT_MODEL=whisper-1")
    raw = [{"start": s.start, "end": s.end, "text": s.text} for s in resp.segments]
    return to_segments(raw), normalize_language(getattr(resp, "language", None))
