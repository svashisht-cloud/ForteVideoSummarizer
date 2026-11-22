"""Unit tests for extract.py: the no-AI "key moments" summary (pure, no network)."""

import pytest

from app.pipeline.errors import PipelineError
from app.pipeline.extract import clean_start, key_moments, rank_blocks, sections_for, tokenize, trim, window_for
from app.pipeline.models import Chapter, Segment


def block(start, text, length=30.0):
    return Segment(start=start, end=start + length, text=text)


# --- tokenize ----------------------------------------------------------------------


def test_tokenize_words_lowercased_without_punctuation():
    assert tokenize("The Field, the FIELD! x", "en") == ["the", "field", "the", "field"]


@pytest.mark.parametrize("lang", ["zh", "ja", "zh-Hans"])
def test_tokenize_cjk_uses_character_bigrams(lang):
    assert tokenize("拖延，会", lang) == ["拖延", "延会"]


# --- rank_blocks ---------------------------------------------------------------------


def test_central_block_ranks_highest_and_offtopic_lowest():
    blocks = [
        block(0, "electric field charges"),
        block(30, "magnetic field charges current"),
        block(60, "electric magnetic field charges current waves"),  # shares with everything
        block(90, "please like and subscribe to the channel"),
    ]
    scores = rank_blocks(blocks, "en")
    assert scores.argmax() == 2
    assert scores.argmin() == 3
    assert scores.sum() == pytest.approx(1.0)


def test_rank_edge_cases():
    assert rank_blocks([], "en").tolist() == []
    assert rank_blocks([block(0, "only one")], "en").tolist() == [1.0]


# --- trim ----------------------------------------------------------------------------


def test_trim_cuts_at_a_word_boundary():
    text = "word " * 100
    out = trim(text, 50)
    assert out.endswith("…")
    assert len(out) <= 51
    assert not out[:-1].endswith(" ")
    assert trim("short text", 50) == "short text"


def test_trim_hard_cuts_text_without_spaces():
    assert trim("拖" * 20, 10) == "拖" * 10 + "…"


# --- sections_for --------------------------------------------------------------------


def test_sections_follow_chapters():
    blocks = [block(t, f"b{t}") for t in range(0, 300, 30)]  # 0..270
    chapters = [Chapter(title="Intro", start=0, end=90), Chapter(title="Main part", start=90, end=None)]
    spans = sections_for(blocks, chapters)
    assert [(s.title, s.indices[0], s.indices[-1]) for s in spans] == [("Intro", 0, 2), ("Main part", 3, 9)]


def test_sections_fall_back_to_time_windows_and_drop_empty_ones():
    blocks = [block(0, "a"), block(30, "b"), block(400, "c"), block(1300, "d")]
    spans = sections_for(blocks, [Chapter(title="Only one chapter", start=0)], window=300)  # <2 chapters: ignored
    assert [(s.title, s.indices) for s in spans] == [
        ("0:00–5:00", [0, 1]),
        ("5:00–10:00", [2]),
        ("20:00–25:00", [3]),
    ]


# --- key_moments ---------------------------------------------------------------------


def test_key_moments_shape():
    texts = ["electric field charges"] * 2 + ["magnetic field current"] * 6 + ["like and subscribe"]
    blocks = [block(i * 30, f"{t} {i}") for i, t in enumerate(texts)]
    s = key_moments(blocks, "en", [Chapter(title="A", start=0, end=120), Chapter(title="B", start=120)])
    assert s.method == "extractive"
    assert s.usage is None
    assert [sec.title for sec in s.sections] == ["A", "B"]
    a, b = s.sections
    assert (a.start, a.end, b.start, b.end) == (0, 120, 120, 270)
    assert len(a.points) == 1  # 4 blocks -> 25% -> 1
    assert len(b.points) == 1  # 5 blocks -> round(1.25) -> 1
    for sec in s.sections:  # points stay in time order and come from their own section
        ts = [p.t for p in sec.points]
        assert ts == sorted(ts) and all(sec.start <= t < sec.end for t in ts)
    assert s.tldr  # the two best blocks overall


def test_key_moments_caps_points_per_section():
    blocks = [block(i * 10, f"topic words number {i}", length=10) for i in range(30)]
    one_chapter = [Chapter(title="All", start=0), Chapter(title="After the end", start=10_000)]
    s = key_moments(blocks, "en", one_chapter)
    assert len(s.sections) == 1
    assert len(s.sections[0].points) == 5


def test_key_moments_rejects_an_empty_transcript():
    with pytest.raises(PipelineError):
        key_moments([], "en", [])


# --- window size and sentence starts -------------------------------------------------


@pytest.mark.parametrize(
    ("duration", "window"),
    [(200, 60), (303, 60), (600, 90), (1800, 300), (3600, 300)],
)
def test_window_scales_with_length(duration, window):
    assert window_for(duration) == window


def test_short_video_gets_several_sections():
    blocks = [block(t, f"words about topic {t}") for t in range(0, 300, 30)]  # 5-minute video
    assert len(sections_for(blocks, [])) == 5


def test_clean_start_skips_a_leading_fragment():
    text = "of the Lorentz force. So Maxwell's equations are not about how charges move, but about the field itself."
    assert clean_start(text) == "So Maxwell's equations are not about how charges move, but about the field itself."


def test_clean_start_keeps_text_without_an_early_sentence_break():
    assert clean_start("no punctuation in auto captions at all here") == "No punctuation in auto captions at all here"
    late = "a long opening clause that goes on and on and on for quite a while before it ends. Short."
    assert clean_start(late) == "A long opening clause that goes on and on and on for quite a while before it ends. Short."


def test_tldr_has_no_doubled_ellipsis():
    blocks = [block(i * 30, ("energy field charge " * 40) + str(i)) for i in range(4)]
    assert "… …" not in key_moments(blocks, "en", []).tldr
