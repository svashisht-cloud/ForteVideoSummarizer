"""Free "key moments": an extractive summary with no LLM.

TextRank over the ~30s caption blocks: TF-IDF vectors, a cosine-similarity
graph, PageRank. The best-connected blocks are the most representative parts
of the video. They're quoted as-is (original language), grouped into the
video's YouTube chapters, or ~5-minute windows when it has none. Returns the
same Summary shape as the AI path, with method="extractive".
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from app.pipeline.errors import PipelineError
from app.pipeline.models import Chapter, Point, Section, Segment, Summary
from app.pipeline.normalize import format_ts

EXTRACT_VERSION = 2  # bump when the algorithm or its settings change (cache key)
TARGET_SECTIONS = 6  # when the video has no chapters, aim for about this many windows…
MIN_WINDOW, MAX_WINDOW = 60.0, 300.0  # …each between 1 and 5 minutes long
SHARE = 0.25  # fraction of a section's blocks kept as points
MAX_POINTS = 5
MAX_POINT_CHARS = 300
TLDR_BLOCKS = 2
DAMPING = 0.85
_NO_SPACES = {"zh", "ja"}  # languages written without spaces: use character bigrams
_WORD = re.compile(r"\w+")


def tokenize(text: str, lang: str) -> list[str]:
    text = text.lower()
    if lang.split("-")[0].lower() in _NO_SPACES:
        chars = [c for c in text if c.isalnum()]
        return [a + b for a, b in zip(chars, chars[1:], strict=False)]
    return [w for w in _WORD.findall(text) if len(w) > 1]


def rank_blocks(blocks: Sequence[Segment], lang: str) -> np.ndarray:
    """TextRank score per block (sums to 1)."""
    n = len(blocks)
    if n == 0:
        return np.zeros(0)
    if n == 1:
        return np.ones(1)
    docs = [Counter(tokenize(b.text, lang)) for b in blocks]
    vocab = {w: i for i, w in enumerate(sorted(set().union(*docs)))}
    df = Counter(w for d in docs for w in d)
    vectors = np.zeros((n, max(len(vocab), 1)))
    for i, d in enumerate(docs):
        total = sum(d.values()) or 1
        for w, c in d.items():
            vectors[i, vocab[w]] = (c / total) * (math.log((1 + n) / (1 + df[w])) + 1)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms > 0)
    sim = vectors @ vectors.T
    np.fill_diagonal(sim, 0.0)
    rows = sim.sum(axis=1, keepdims=True)
    # A block with no overlap at all links to everyone equally (standard PageRank fix).
    trans = np.where(rows > 0, sim / np.where(rows > 0, rows, 1), 1.0 / n)
    scores = np.full(n, 1.0 / n)
    for _ in range(200):
        nxt = (1 - DAMPING) / n + DAMPING * trans.T @ scores
        if np.abs(nxt - scores).sum() < 1e-10:
            scores = nxt
            break
        scores = nxt
    return scores / scores.sum()


_SENTENCE_END = re.compile(r"[.!?。！？](?:\s+|$)")


def clean_start(text: str) -> str:
    """Caption blocks start mid-sentence. If a sentence ends early in the block
    (first ~40%), start after it. Captions without punctuation are left as is.
    The first letter is capitalized."""
    text = " ".join(text.split())
    m = _SENTENCE_END.search(text)
    if m and m.end() <= len(text) * 0.4 and len(text) - m.end() >= 40:
        text = text[m.end():]
    return text[:1].upper() + text[1:]


def window_for(duration: float) -> float:
    """Section length for videos without chapters, rounded to 30 s."""
    raw = min(MAX_WINDOW, max(MIN_WINDOW, duration / TARGET_SECTIONS))
    return max(MIN_WINDOW, round(raw / 30) * 30)


def trim(text: str, limit: int = MAX_POINT_CHARS) -> str:
    """Shorten at a word boundary (or hard, for text without spaces), adding "…"."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "…"


@dataclass
class Span:
    title: str
    indices: list[int]  # blocks in this section, in order


def sections_for(
    blocks: Sequence[Segment], chapters: Sequence[Chapter], window: float | None = None
) -> list[Span]:
    """Group blocks by YouTube chapter (when there are at least 2), else by fixed
    windows sized to the video's length."""
    if len(chapters) >= 2:
        ordered = sorted(chapters, key=lambda c: c.start)
        starts = [c.start for c in ordered]
        titles = [c.title.strip() or f"Part {i + 1}" for i, c in enumerate(ordered)]
    else:
        last = blocks[-1].start if blocks else 0.0
        window = window or window_for(blocks[-1].end if blocks else 0.0)
        starts = [k * window for k in range(int(last // window) + 1)]
        titles = [f"{format_ts(s)}–{format_ts(s + window)}" for s in starts]
    spans = [Span(t, []) for t in titles]
    for i, b in enumerate(blocks):
        k = max(j for j, s in enumerate(starts) if s <= b.start) if b.start >= starts[0] else 0
        spans[k].indices.append(i)
    return [s for s in spans if s.indices]


def key_moments(blocks: Sequence[Segment], lang: str, chapters: Sequence[Chapter] = ()) -> Summary:
    if not blocks:
        raise PipelineError("transcript is empty after cleaning")
    scores = rank_blocks(blocks, lang)
    sections = []
    for span in sections_for(blocks, chapters):
        k = min(MAX_POINTS, max(1, round(len(span.indices) * SHARE)))
        best = sorted(sorted(span.indices, key=lambda i: -scores[i])[:k])
        sections.append(
            Section(
                title=span.title,
                start=blocks[span.indices[0]].start,
                end=blocks[span.indices[-1]].end,
                points=[Point(t=blocks[i].start, text=trim(clean_start(blocks[i].text))) for i in best],
            )
        )
    top = sorted(np.argsort(-scores, kind="stable")[:TLDR_BLOCKS].tolist())
    parts = [trim(clean_start(blocks[i].text), 220) for i in top]
    tldr = " … ".join(p.removesuffix("…") for p in parts) + ("…" if parts[-1].endswith("…") else "")
    return Summary(tldr=tldr, sections=sections, usage=None, method="extractive")
