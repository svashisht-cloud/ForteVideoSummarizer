"""Pure transcript helpers: clean, merge into blocks, chunk, timestamp formatting."""

import html
import re

from app.pipeline.models import Segment

# A bracketed caption tag such as [Music], [Applause], [Музыка]. Real speech
# in auto and human captions is never bracketed, so any short bracketed span
# is treated as a non-speech tag.
_SOUND_TAG = re.compile(r"\[[^\[\]]{1,40}\]")
_WHITESPACE = re.compile(r"\s+")
_TS = re.compile(r"^(?:(\d+):([0-5]\d)|(\d+):([0-5]\d):([0-5]\d))$")


def clean_text(text: str) -> str:
    """Unescape HTML entities, drop sound tags, collapse whitespace."""
    text = html.unescape(text)
    text = _SOUND_TAG.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def normalize(segments: list[Segment], window: float = 30.0) -> list[Segment]:
    """Merge consecutive segments into blocks of about `window` seconds.

    A block closes once its duration (last end - first start) reaches
    `window`. A segment that starts `window` or more after the current
    block's start opens a new block, so a long gap never stretches a block.
    Segments whose text is empty after cleaning are skipped.
    """
    blocks: list[Segment] = []
    start = end = 0.0
    texts: list[str] = []

    def close() -> None:
        if texts:
            blocks.append(Segment(start=start, end=end, text=" ".join(texts)))
            texts.clear()

    for s in segments:
        text = clean_text(s.text)
        if not text:
            continue
        if texts and s.start - start >= window:
            close()
        if not texts:
            start, end = s.start, s.end
        else:
            end = max(end, s.end)
        texts.append(text)
        if end - start >= window:
            close()

    close()
    return blocks


def chunk(blocks: list[Segment], minutes: float = 12) -> list[list[Segment]]:
    """Group blocks into chunks spanning about `minutes` each.

    A new chunk starts at the first block that begins `minutes` or more after
    the current chunk's first block. Blocks are never split.
    """
    limit = minutes * 60
    chunks: list[list[Segment]] = []
    for b in blocks:
        if not chunks or b.start - chunks[-1][0].start >= limit:
            chunks.append([])
        chunks[-1].append(b)
    return chunks


def format_ts(seconds: float) -> str:
    """Seconds -> "m:ss", or "h:mm:ss" from one hour up. Fractions are dropped."""
    if seconds < 0:
        raise ValueError(f"negative timestamp: {seconds}")
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_ts(text: str) -> int:
    """Inverse of format_ts: "m:ss" or "h:mm:ss" -> seconds.

    Surrounding whitespace and [brackets] are tolerated, since the timestamp
    usually comes from an "[m:ss]" prompt marker.
    """
    t = text.strip().removeprefix("[").removesuffix("]").strip()
    match = _TS.match(t)
    if not match:
        raise ValueError(f"invalid timestamp: {text!r}")
    m, s, h2, m2, s2 = match.groups()
    if m is not None:
        return int(m) * 60 + int(s)
    return int(h2) * 3600 + int(m2) * 60 + int(s2)


def to_prompt_text(blocks: list[Segment]) -> str:
    """One "[m:ss] text" line per block."""
    return "\n".join(f"[{format_ts(b.start)}] {b.text}" for b in blocks)
