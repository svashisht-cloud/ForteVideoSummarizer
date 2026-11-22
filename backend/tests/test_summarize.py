"""Unit tests for summarize.py. The OpenAI client is faked; nothing hits the network."""

import asyncio
import logging
import re
from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.pipeline.errors import PipelineError
from app.pipeline.models import (
    ChunkPoints,
    LLMPoint,
    LLMSection,
    LLMSummary,
    Point,
    Section,
    Segment,
    Summary,
    Usage,
)
from app.pipeline.summarize import (
    PROMPT_VERSION,
    build_summary,
    resolve_model,
    resolve_ts,
    snap,
    summarize,
)

MARKER = re.compile(r"^\[(\d+(?::\d\d){1,2})\]", re.M)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def seg(start, end, text="word"):
    return Segment(start=start, end=end, text=text)


def even_segments(total_seconds, step=5.0):
    n = int(total_seconds / step)
    return [seg(i * step, (i + 1) * step, f"s{i}") for i in range(n)]


def blocks_every(seconds, count):
    return [seg(i * seconds, (i + 1) * seconds, f"b{i}") for i in range(count)]


def fake_usage(input_tokens, cached, output_tokens):
    return SimpleNamespace(
        input_tokens=input_tokens,
        input_tokens_details=SimpleNamespace(cached_tokens=cached),
        output_tokens=output_tokens,
    )


class FakeStream:
    def __init__(self, owner, kwargs):
        self.owner, self.kwargs = owner, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_response(self):
        o = self.owner
        o.in_flight += 1
        o.max_in_flight = max(o.max_in_flight, o.in_flight)
        try:
            await asyncio.sleep(0.01)
            return SimpleNamespace(output_parsed=o.handler(self.kwargs), usage=o.usage)
        finally:
            o.in_flight -= 1


class FakeResponses:
    """Stands in for client.responses (streaming). `handler(kwargs)` returns output_parsed."""

    def __init__(self, handler):
        self.handler = handler
        self.usage = fake_usage(1000, 100, 200)
        self.calls = []
        self.in_flight = 0
        self.max_in_flight = 0

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self, kwargs)


def fake_client(handler):
    return SimpleNamespace(responses=FakeResponses(handler))


def markers(text):
    return MARKER.findall(text)


# --- snap / resolve_ts ---------------------------------------------------------

STARTS = [0.0, 30.0, 60.0, 90.0]


@pytest.mark.parametrize(
    "seconds, expected",
    [(0, 0), (30, 30), (40, 30), (50, 60), (45, 30), (-5, 0), (500, 90), (89, 90)],
)
def test_snap(seconds, expected):
    assert snap(seconds, STARTS) == expected


def test_snap_unsorted_offsets():
    # Block starts aren't always on a grid.
    assert snap(14, [0.0, 12.5, 31.0]) == 12.5


@pytest.mark.parametrize("ts, expected", [("0:31", 30), ("[1:29]", 90), (" 1:00 ", 60)])
def test_resolve_ts(ts, expected):
    assert resolve_ts(ts, STARTS, fallback=0) == expected


def test_resolve_ts_hours():
    starts = [3600.0, 3630.0]
    assert resolve_ts("1:00:29", starts, fallback=0) == 3630


def test_resolve_ts_unparseable_uses_fallback_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        assert resolve_ts("about 5 min", STARTS, fallback=60) == 60
    assert "about 5 min" in caplog.text


# --- build_summary ---------------------------------------------------------------


def test_build_summary_sets_section_bounds_from_points():
    blocks = blocks_every(30, 4)  # 0-30, 30-60, 60-90, 90-120
    llm = LLMSummary(
        tldr="  The gist.  ",
        sections=[
            LLMSection(
                title=" Intro ",
                points=[LLMPoint(ts="0:05", text="a"), LLMPoint(ts="0:31", text="b")],
            ),
            LLMSection(title="Main", points=[LLMPoint(ts="1:30", text="c")]),
        ],
    )
    assert build_summary(llm, blocks) == Summary(
        tldr="The gist.",
        sections=[
            Section(title="Intro", start=0, end=60, points=[Point(t=0, text="a"), Point(t=30, text="b")]),
            Section(title="Main", start=90, end=120, points=[Point(t=90, text="c")]),
        ],
    )


def test_build_summary_sorts_points_and_sections():
    blocks = blocks_every(30, 4)
    llm = LLMSummary(
        tldr="x",
        sections=[
            LLMSection(title="Late", points=[LLMPoint(ts="1:30", text="z")]),
            LLMSection(
                title="Early",
                points=[LLMPoint(ts="1:00", text="y"), LLMPoint(ts="0:00", text="x")],
            ),
        ],
    )
    out = build_summary(llm, blocks)
    assert [s.title for s in out.sections] == ["Early", "Late"]
    assert [p.text for p in out.sections[0].points] == ["x", "y"]
    assert (out.sections[0].start, out.sections[0].end) == (0, 90)


def test_build_summary_drops_blank_points_and_empty_sections():
    blocks = blocks_every(30, 2)
    llm = LLMSummary(
        tldr="x",
        sections=[
            LLMSection(title="Keep", points=[LLMPoint(ts="0:00", text="ok"), LLMPoint(ts="0:30", text="  ")]),
            LLMSection(title="Empty", points=[]),
            LLMSection(title="Blank only", points=[LLMPoint(ts="0:30", text="")]),
        ],
    )
    out = build_summary(llm, blocks)
    assert [s.title for s in out.sections] == ["Keep"]
    assert out.sections[0].points == [Point(t=0, text="ok")]


def test_build_summary_bad_ts_falls_back_to_previous_point():
    blocks = blocks_every(30, 4)
    llm = LLMSummary(
        tldr="x",
        sections=[
            LLMSection(
                title="S",
                points=[LLMPoint(ts="1:00", text="a"), LLMPoint(ts="??", text="b")],
            )
        ],
    )
    pts = build_summary(llm, blocks).sections[0].points
    assert [(p.t, p.text) for p in pts] == [(60, "a"), (60, "b")]


def test_build_summary_bad_first_ts_falls_back_to_first_block():
    blocks = [seg(12, 40, "a"), seg(40, 70, "b")]
    llm = LLMSummary(tldr="x", sections=[LLMSection(title="S", points=[LLMPoint(ts="nope", text="a")])])
    assert build_summary(llm, blocks).sections[0].points[0].t == 12


# --- summarize: single-chunk path --------------------------------------------------


@pytest.mark.anyio
async def test_single_chunk_makes_one_call():
    segments = even_segments(5 * 60)

    def handler(kw):
        assert kw["text_format"] is LLMSummary
        ms = markers(kw["input"])
        return LLMSummary(
            tldr="Short video.",
            sections=[LLMSection(title="All", points=[LLMPoint(ts=ms[0], text="p1"), LLMPoint(ts=ms[3], text="p2")])],
        )

    client = fake_client(handler)
    progress = []
    out = await summarize(
        segments, "en", lambda *a: progress.append(a), client=client, model="test-model"
    )

    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]
    assert call["model"] == "test-model"
    assert "English" in call["instructions"]
    assert progress == [("summarizing", 1, 1)]
    assert out == Summary(
        tldr="Short video.",
        sections=[Section(title="All", start=0, end=120, points=[Point(t=0, text="p1"), Point(t=90, text="p2")])],
        usage=Usage(
            model="test-model", calls=1, input_tokens=1000, cached_input_tokens=100, output_tokens=200, cost_usd=None
        ),
    )


@pytest.mark.anyio
async def test_unknown_language_passed_through():
    client = fake_client(lambda kw: LLMSummary(tldr="x", sections=[]))
    await summarize(even_segments(60), "Klingon", client=client, model="m")
    assert "Klingon" in client.responses.calls[0]["instructions"]


@pytest.mark.anyio
async def test_language_code_mapped_to_name():
    client = fake_client(lambda kw: LLMSummary(tldr="x", sections=[]))
    await summarize(even_segments(60), "es", client=client, model="m")
    assert "Spanish" in client.responses.calls[0]["instructions"]


# --- summarize: map-reduce path ------------------------------------------------------


@pytest.mark.anyio
async def test_map_reduce_three_chunks():
    segments = even_segments(30 * 60)  # 60 blocks of 30s -> chunks at 0, 12, 24 min
    merge_inputs = []

    def handler(kw):
        if kw["text_format"] is ChunkPoints:
            ms = markers(kw["input"])
            # One real marker, plus a made-up one far outside the chunk.
            return ChunkPoints(points=[LLMPoint(ts=ms[1], text=f"point at {ms[1]}"), LLMPoint(ts="59:00", text="stray")])
        assert kw["text_format"] is LLMSummary
        merge_inputs.append(kw["input"])
        ms = markers(kw["input"])
        return LLMSummary(
            tldr="Long video.",
            sections=[
                LLMSection(title="B", points=[LLMPoint(ts=ms[2], text="second")]),
                LLMSection(title="A", points=[LLMPoint(ts=ms[0], text="first")]),
            ],
        )

    client = fake_client(handler)
    progress = []
    out = await summarize(segments, "en", lambda *a: progress.append(a), client=client, model="m")

    assert len(client.responses.calls) == 4
    assert [c["text_format"] for c in client.responses.calls[:3]] == [ChunkPoints] * 3
    # Stray "59:00" snaps to each chunk's own last block, not the video's.
    assert markers(merge_inputs[0]) == ["0:30", "11:30", "12:30", "23:30", "24:30", "29:30"]
    assert "point at 12:30" in merge_inputs[0]
    assert progress == [
        ("summarizing", 0, 3),
        ("summarizing", 1, 3),
        ("summarizing", 2, 3),
        ("summarizing", 3, 3),
        ("merging", 0, 1),
    ]
    assert [(s.title, s.start, s.end) for s in out.sections] == [("A", 30, 60), ("B", 750, 780)]
    # Usage sums all 4 calls (3 maps + merge).
    assert (out.usage.calls, out.usage.input_tokens, out.usage.cached_input_tokens, out.usage.output_tokens) == (
        4, 4000, 400, 800,
    )  # fmt: skip


@pytest.mark.anyio
async def test_usage_priced_for_known_model():
    client = fake_client(lambda kw: LLMSummary(tldr="x", sections=[]))
    out = await summarize(even_segments(60), "en", client=client, model="gpt-6.1-terra")
    # 900 uncached * $1 + 100 cached * $0.05 + 200 output * $5, per 1M tokens
    assert out.usage.cost_usd == pytest.approx((900 * 1 + 100 * 0.05 + 200 * 5) / 1_000_000)


@pytest.mark.anyio
async def test_missing_usage_counts_as_zero():
    client = fake_client(lambda kw: LLMSummary(tldr="x", sections=[]))
    client.responses.usage = None
    out = await summarize(even_segments(60), "en", client=client, model="gpt-6.1-terra")
    assert (out.usage.calls, out.usage.input_tokens, out.usage.output_tokens) == (1, 0, 0)


@pytest.mark.anyio
async def test_map_concurrency_capped_at_four():
    segments = even_segments(96 * 60)  # 8 chunks

    def handler(kw):
        if kw["text_format"] is ChunkPoints:
            return ChunkPoints(points=[LLMPoint(ts=markers(kw["input"])[0], text="p")])
        return LLMSummary(tldr="x", sections=[])

    client = fake_client(handler)
    await summarize(segments, "en", client=client, model="m")
    map_calls = [c for c in client.responses.calls if c["text_format"] is ChunkPoints]
    assert len(map_calls) == 8
    assert client.responses.max_in_flight == 4


@pytest.mark.anyio
async def test_zero_point_chunk_logs_warning(caplog):
    segments = even_segments(30 * 60)

    def handler(kw):
        if kw["text_format"] is ChunkPoints:
            if kw["input"].startswith("Transcript part 2 of 3"):
                return ChunkPoints(points=[])
            return ChunkPoints(points=[LLMPoint(ts=markers(kw["input"])[0], text="p")])
        return LLMSummary(tldr="x", sections=[])

    with caplog.at_level(logging.WARNING):
        await summarize(segments, "en", client=fake_client(handler), model="m")
    assert "chunk 2/3" in caplog.text
    assert "zero points" in caplog.text


# --- errors ------------------------------------------------------------------------


@pytest.mark.anyio
async def test_refusal_raises():
    client = fake_client(lambda kw: None)
    with pytest.raises(PipelineError, match="no structured output"):
        await summarize(even_segments(60), "en", client=client, model="m")


@pytest.mark.anyio
async def test_openai_error_becomes_pipeline_error():
    def handler(kw):
        raise openai.APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com/v1/responses"))

    with pytest.raises(PipelineError, match="OpenAI request failed for summary") as exc:
        await summarize(even_segments(60), "en", client=fake_client(handler), model="m")
    assert isinstance(exc.value.__cause__, openai.APIConnectionError)


@pytest.mark.anyio
async def test_map_refusal_names_chunk():
    def handler(kw):
        return None if kw["input"].startswith("Transcript part 3") else ChunkPoints(points=[])

    with pytest.raises(PipelineError, match="chunk 3/3"):
        await summarize(even_segments(30 * 60), "en", client=fake_client(handler), model="m")


@pytest.mark.anyio
async def test_missing_model_env_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    client = fake_client(lambda kw: LLMSummary(tldr="x", sections=[]))
    with pytest.raises(PipelineError, match="OPENAI_MODEL"):
        await summarize(even_segments(60), "en", client=client)
    assert client.responses.calls == []


@pytest.mark.anyio
async def test_model_read_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    client = fake_client(lambda kw: LLMSummary(tldr="x", sections=[]))
    await summarize(even_segments(60), "en", client=client)
    assert client.responses.calls[0]["model"] == "env-model"


@pytest.mark.anyio
async def test_empty_transcript_raises():
    client = fake_client(lambda kw: None)
    with pytest.raises(PipelineError, match="empty"):
        await summarize([seg(0, 2, "[Music]")], "en", client=client, model="m")
    assert client.responses.calls == []


# --- resolve_model / PROMPT_VERSION -----------------------------------------------


def test_resolve_model_prefers_argument(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "env-model")
    assert resolve_model("explicit") == "explicit"
    assert resolve_model() == "env-model"


def test_resolve_model_missing_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(PipelineError, match="OPENAI_MODEL"):
        resolve_model()


def test_prompt_version_is_positive_int():
    assert isinstance(PROMPT_VERSION, int) and PROMPT_VERSION >= 1
