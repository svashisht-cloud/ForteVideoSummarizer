"""All LLM calls: map (points per chunk) and merge (sections + TL;DR).

The LLM reads the original-language transcript and writes directly in the
target language. It returns timestamps as the exact "m:ss" marker strings it
was given; code parses them and snaps each to the nearest block start.
"""

import asyncio
import bisect
import logging
import os
from collections.abc import Callable

from pydantic import BaseModel

from app.pipeline.errors import PipelineError
from app.pipeline.llm import LLM, OpenAILLM, TokenCount, make_llm
from app.pipeline.models import (
    ChunkPoints,
    LLMPoint,
    LLMSummary,
    Point,
    Section,
    Segment,
    Summary,
    Usage,
)
from app.pipeline.normalize import chunk, format_ts, normalize, parse_ts, to_prompt_text
from app.pipeline.pricing import cost_usd

log = logging.getLogger(__name__)

MAX_CONCURRENT_MAPS = 4

# Bump whenever the prompts, the LLM-facing models, or post-processing change
# in a way that changes summaries. Cached summaries from another version (or
# another model) are treated as misses.
PROMPT_VERSION = 1

ProgressFn = Callable[[str, int, int], None]

LANG_NAMES = {
    "ar": "Arabic", "bn": "Bengali", "de": "German", "en": "English",
    "es": "Spanish", "fa": "Persian", "fr": "French", "hi": "Hindi",
    "id": "Indonesian", "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "nl": "Dutch", "pl": "Polish", "pt": "Portuguese", "ru": "Russian",
    "sv": "Swedish", "ta": "Tamil", "te": "Telugu", "th": "Thai",
    "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu", "vi": "Vietnamese",
    "zh": "Chinese",
}  # fmt: skip


def resolve_model(model: str | None = None) -> str:
    """The model to use: the argument, else OPENAI_MODEL."""
    model = model or os.environ.get("OPENAI_MODEL")
    if not model:
        raise PipelineError("OPENAI_MODEL is not set; add it to backend/.env")
    return model


def language_name(target_lang: str) -> str:
    return LANG_NAMES.get(target_lang.strip().lower(), target_lang.strip())


# --- Prompts -------------------------------------------------------------------

_INTRO_TRANSCRIPT = """\
The transcript can be in any language. Each line starts with a timestamp
marker like [12:34], followed by what is said from that moment on."""

_POINT_RULES = """\
- One point per idea. State the idea itself in one or two sentences (the
  claim, fact, step, example, number or conclusion), not "the speaker
  talks about X".
- Keep specifics: names, numbers, dates, products, steps.
- Leave out filler, greetings, "like and subscribe", sponsor reads and ads,
  and anything repeated. List each idea once."""

_TS_RULE_TRANSCRIPT = """\
For each point, set ts to the marker of the line where the point is made,
copied exactly as written, without the brackets (for example "12:34" or
"1:02:03"). Use only markers that appear in the transcript."""

_GROUP_RULE = """\
Group the points into sections by topic. Sections follow the order of
   the video, and each one covers a run of consecutive points. Use as many
   sections as there are topics. Give each a short, specific title."""

_KEEP_RULE = """\
Keep every distinct point, even minor ones. You can tighten the
   wording, but add nothing that is not in the points."""

_TLDR_RULE = """\
Write a TL;DR of 2-3 sentences: what the video is about and its main
   takeaways."""

MAP_PROMPT = f"""\
You extract the content of one part of a video transcript.

{_INTRO_TRANSCRIPT}

Write every point in {{lang}}, whatever language the transcript is in.

List every distinct point made in this part, in the order it is made:
{_POINT_RULES}
- If this part has no real content, return an empty list.

{_TS_RULE_TRANSCRIPT}
"""

MERGE_PROMPT = f"""\
You turn notes from a video into a structured summary.

The input lists points taken from consecutive parts of one video, in
chronological order. Each line is "[m:ss] point". The parts were processed
separately, so the same point can appear more than once, usually near a
part boundary.

Write everything in {{lang}}.

1. {_GROUP_RULE}
2. Merge duplicates: when two points say the same thing, keep one, with
   the earlier timestamp.
3. {_KEEP_RULE}
4. {_TLDR_RULE}

For each point, set ts to the timestamp of the point it came from, copied
exactly as written, without the brackets.
"""

SINGLE_PROMPT = f"""\
You summarize a video from its transcript.

{_INTRO_TRANSCRIPT}

Write everything in {{lang}}, whatever language the transcript is in.

First find every distinct point made in the video:
{_POINT_RULES}

Then:
1. {_GROUP_RULE}
2. {_KEEP_RULE}
3. {_TLDR_RULE}

{_TS_RULE_TRANSCRIPT}
"""


# --- Post-processing (pure) ------------------------------------------------------


def snap(seconds: float, block_starts: list[float]) -> float:
    """Nearest block start; ties go to the earlier block. `block_starts` sorted."""
    i = bisect.bisect_left(block_starts, seconds)
    if i == 0:
        return block_starts[0]
    if i == len(block_starts):
        return block_starts[-1]
    before, after = block_starts[i - 1], block_starts[i]
    return after if after - seconds < seconds - before else before


def resolve_ts(ts: str, block_starts: list[float], fallback: float) -> float:
    """Parse an LLM "m:ss" string and snap it. Unparseable -> `fallback`."""
    try:
        seconds = parse_ts(ts)
    except ValueError:
        log.warning("LLM returned unparseable timestamp %r; using %s", ts, format_ts(fallback))
        return fallback
    return snap(seconds, block_starts)


def _resolve_points(points: list[LLMPoint], block_starts: list[float], fallback: float) -> list[Point]:
    out: list[Point] = []
    for p in points:
        text = p.text.strip()
        if not text:
            continue
        prev = out[-1].t if out else fallback
        out.append(Point(t=resolve_ts(p.ts, block_starts, prev), text=text))
    return out


def build_summary(llm: LLMSummary, blocks: list[Segment]) -> Summary:
    """Turn the LLM's string timestamps into a Summary with snapped seconds."""
    starts = [b.start for b in blocks]
    end_of = {b.start: b.end for b in blocks}
    sections: list[Section] = []
    fallback = starts[0]
    for s in llm.sections:
        points = _resolve_points(s.points, starts, fallback)
        if not points:
            continue
        points.sort(key=lambda p: p.t)
        fallback = points[-1].t
        sections.append(
            Section(
                title=s.title.strip(),
                start=points[0].t,
                end=end_of[points[-1].t],
                points=points,
            )
        )
    sections.sort(key=lambda s: s.start)
    return Summary(tldr=llm.tldr.strip(), sections=sections)


# --- LLM calls ---------------------------------------------------------------------


def _add_counts(total: Usage, counts: TokenCount) -> None:
    total.calls += 1
    total.input_tokens += counts.input_tokens
    total.cached_input_tokens += counts.cached_input_tokens
    total.output_tokens += counts.output_tokens


def _priced(usage: Usage) -> Usage:
    usage.cost_usd = cost_usd(usage.model, usage.input_tokens, usage.cached_input_tokens, usage.output_tokens)
    return usage


async def _call[T: BaseModel](llm: LLM, instructions: str, input: str, fmt: type[T], what: str, usage: Usage) -> T:
    """One structured LLM call; adds its tokens to `usage` (also when the result is unusable)."""
    parsed, counts = await llm.structured(instructions, input, fmt, what)
    _add_counts(usage, counts)
    return parsed


async def summarize(
    segments: list[Segment],
    target_lang: str,
    on_progress: ProgressFn | None = None,
    *,
    llm: LLM | None = None,
    model: str | None = None,
    api_key: str | None = None,
    client=None,
) -> Summary:
    """Summarize a transcript in `target_lang` (a code like "en" or a language name).

    The provider (OpenAI or Claude) follows the model; `api_key` is the user's key
    for it (None: the server's). `llm` or an OpenAI `client` can be injected (tests)."""
    if llm is not None:
        model = llm.model
    else:
        model = resolve_model(model)
    owned = llm is None
    if llm is None:
        llm = OpenAILLM(model, client=client) if client is not None else make_llm(model, api_key)
    try:
        return await _summarize(llm, segments, target_lang, on_progress)
    finally:
        if owned:
            await llm.aclose()


async def _summarize(llm: LLM, segments: list[Segment], target_lang: str, on_progress: ProgressFn | None) -> Summary:
    model = llm.model

    blocks = normalize(segments)
    if not blocks:
        raise PipelineError("transcript is empty after cleaning")
    chunks = chunk(blocks)
    lang = language_name(target_lang)
    progress = on_progress or (lambda stage, done, total: None)
    usage = Usage(model=model)

    if len(chunks) == 1:
        written = await _call(
            llm, SINGLE_PROMPT.format(lang=lang), to_prompt_text(blocks), LLMSummary, "summary", usage
        )
        progress("summarizing", 1, 1)
        return build_summary(written, blocks).model_copy(update={"usage": _priced(usage)})

    n = len(chunks)
    progress("summarizing", 0, n)
    sem = asyncio.Semaphore(MAX_CONCURRENT_MAPS)
    done = 0

    async def map_chunk(i: int, blocks_i: list[Segment]) -> list[Point]:
        nonlocal done
        what = f"chunk {i + 1}/{n}"
        async with sem:
            result = await _call(
                llm,
                MAP_PROMPT.format(lang=lang),
                f"Transcript part {i + 1} of {n}:\n\n{to_prompt_text(blocks_i)}",
                ChunkPoints,
                what,
                usage,
            )
        done += 1
        progress("summarizing", done, n)
        # Snap to this chunk's own blocks so a stray timestamp stays in its chunk.
        starts = [b.start for b in blocks_i]
        points = _resolve_points(result.points, starts, starts[0])
        if not points:
            log.warning(
                "%s (%s-%s) returned zero points",
                what, format_ts(blocks_i[0].start), format_ts(blocks_i[-1].end),
            )  # fmt: skip
        return points

    per_chunk = await asyncio.gather(*(map_chunk(i, c) for i, c in enumerate(chunks)))

    progress("merging", 0, 1)
    merge_input = "\n".join(f"[{format_ts(p.t)}] {p.text}" for pts in per_chunk for p in pts)
    if not merge_input:
        raise PipelineError("no points were extracted from any chunk")
    merged = await _call(llm, MERGE_PROMPT.format(lang=lang), merge_input, LLMSummary, "merge", usage)
    return build_summary(merged, blocks).model_copy(update={"usage": _priced(usage)})
