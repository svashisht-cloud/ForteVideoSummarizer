import pytest

from app.pipeline.models import Segment
from app.pipeline.normalize import chunk, format_ts, normalize, parse_ts, to_prompt_text


def seg(start, end, text="word"):
    return Segment(start=start, end=end, text=text)


def even_segments(total_seconds, step=5.0):
    """Back-to-back segments of `step` seconds covering `total_seconds`."""
    n = int(total_seconds / step)
    return [seg(i * step, (i + 1) * step, f"s{i}") for i in range(n)]


# --- normalize -------------------------------------------------------------


def test_normalize_empty():
    assert normalize([]) == []


def test_normalize_one_short_segment():
    assert normalize([seg(1.0, 3.0, "hello")]) == [seg(1.0, 3.0, "hello")]


def test_block_closes_exactly_on_window():
    segs = [seg(0, 10, "a"), seg(10, 20, "b"), seg(20, 30, "c"), seg(30, 35, "d")]
    assert normalize(segs) == [seg(0, 30, "a b c"), seg(30, 35, "d")]


def test_block_stays_open_just_under_window():
    segs = [seg(0, 10, "a"), seg(10, 29.9, "b"), seg(29.9, 35, "c")]
    assert normalize(segs) == [seg(0, 35, "a b c")]


def test_single_segment_longer_than_window_is_its_own_block():
    segs = [seg(0, 5, "a"), seg(5, 50, "long"), seg(50, 55, "b")]
    # "a"+"long" reaches the window at 50s; "b" starts a new block.
    assert normalize(segs) == [seg(0, 50, "a long"), seg(50, 55, "b")]
    assert normalize([seg(0, 90, "long")]) == [seg(0, 90, "long")]


def test_custom_window():
    segs = even_segments(30, step=5)  # six 5s segments
    assert [(b.start, b.end) for b in normalize(segs, window=10)] == [
        (0, 10),
        (10, 20),
        (20, 30),
    ]


def test_small_gap_stays_in_block():
    segs = [seg(0, 5, "a"), seg(8, 12, "b")]
    assert normalize(segs) == [seg(0, 12, "a b")]


def test_large_gap_starts_new_block():
    # A segment starting a full window after the block start must not be
    # merged, or its timestamp would point far before where it is said.
    segs = [seg(0, 5, "a"), seg(100, 105, "b"), seg(106, 110, "c")]
    assert normalize(segs) == [seg(0, 5, "a"), seg(100, 110, "b c")]


def test_overlapping_segments_use_max_end():
    segs = [seg(0, 6, "a"), seg(4, 5, "b")]
    assert normalize(segs) == [seg(0, 6, "a b")]


def test_whitespace_and_newlines_collapsed():
    segs = [seg(0, 2, "hello\nthere"), seg(2, 4, "  big \t\n world  ")]
    assert normalize(segs)[0].text == "hello there big world"


def test_html_entities_unescaped():
    segs = [seg(0, 2, "rock &amp; roll"), seg(2, 4, "it&#39;s &quot;fine&quot;")]
    assert normalize(segs)[0].text == 'rock & roll it\'s "fine"'


def test_sound_tags_dropped():
    segs = [
        seg(0, 2, "[Music]"),
        seg(2, 4, "[Applause] thanks everyone"),
        seg(4, 6, "so [Laughter] anyway"),
    ]
    assert normalize(segs) == [seg(2, 6, "thanks everyone so anyway")]


def test_only_sound_tags_gives_empty_output():
    assert normalize([seg(0, 2, "[Music]"), seg(2, 4, " [ Applause ] ")]) == []


def test_empty_segment_does_not_affect_block_timing():
    # The dropped [Music] at 0-20 must not become the block start.
    segs = [seg(0, 20, "[Music]"), seg(20, 25, "hi"), seg(25, 45, "there")]
    assert normalize(segs) == [seg(20, 45, "hi there")]


def test_non_english_sound_tag_dropped():
    assert normalize([seg(0, 2, "[Музыка]"), seg(2, 4, "привет")]) == [
        seg(2, 4, "привет")
    ]


# --- chunk -----------------------------------------------------------------


def test_chunk_empty():
    assert chunk([]) == []


def test_chunk_five_minute_transcript_is_one_chunk():
    blocks = normalize(even_segments(5 * 60))
    chunks = chunk(blocks)
    assert len(chunks) == 1
    assert chunks[0] == blocks


def test_chunk_thirty_minute_transcript():
    blocks = normalize(even_segments(30 * 60))
    chunks = chunk(blocks)
    assert len(chunks) == 3
    assert [c[0].start for c in chunks] == [0, 12 * 60, 24 * 60]
    # Nothing lost, nothing reordered, no block split.
    assert [b for c in chunks for b in c] == blocks


def test_chunk_spans_at_most_the_chunk_length():
    blocks = normalize(even_segments(30 * 60))
    for c in chunk(blocks, minutes=12):
        assert c[-1].start - c[0].start < 12 * 60


def test_chunk_custom_minutes():
    blocks = normalize(even_segments(10 * 60))
    assert len(chunk(blocks, minutes=5)) == 2


# --- format_ts / parse_ts ----------------------------------------------------


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "0:00"),
        (5, "0:05"),
        (59.9, "0:59"),
        (60, "1:00"),
        (754, "12:34"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
        (36000 + 59, "10:00:59"),
    ],
)
def test_format_ts(seconds, expected):
    assert format_ts(seconds) == expected


def test_format_ts_negative_rejected():
    with pytest.raises(ValueError):
        format_ts(-1)


@pytest.mark.parametrize(
    "text, expected",
    [("0:00", 0), ("0:05", 5), ("12:34", 754), ("1:00:00", 3600), ("1:01:01", 3661)],
)
def test_parse_ts(text, expected):
    assert parse_ts(text) == expected


def test_parse_ts_tolerates_whitespace_and_brackets():
    assert parse_ts(" [1:23] ") == 83


@pytest.mark.parametrize("bad", ["", "abc", "1:2", "1:60", "1:00:60", "1:60:00", "-1:00", "1:2:3:4", "1.5:00"])
def test_parse_ts_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_ts(bad)


@pytest.mark.parametrize("seconds", [0, 1, 59, 60, 61, 599, 3599, 3600, 3601, 7322, 86399])
def test_round_trip(seconds):
    assert parse_ts(format_ts(seconds)) == seconds


# --- to_prompt_text ------------------------------------------------------------


def test_to_prompt_text():
    blocks = [seg(0, 30, "intro"), seg(30.4, 60, "next"), seg(3725, 3750, "late")]
    assert to_prompt_text(blocks) == "[0:00] intro\n[0:30] next\n[1:02:05] late"


def test_to_prompt_text_empty():
    assert to_prompt_text([]) == ""
