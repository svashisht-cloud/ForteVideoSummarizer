import pytest
from pydantic import ValidationError

from app.pipeline.models import Segment


def test_valid_segment():
    s = Segment(start=1.5, end=3.0, text="hello")
    assert (s.start, s.end, s.text) == (1.5, 3.0, "hello")


def test_zero_length_segment_allowed():
    assert Segment(start=2.0, end=2.0, text="x").end == 2.0


def test_text_is_stripped():
    assert Segment(start=0, end=1, text="  hi  \n").text == "hi"


def test_end_before_start_rejected():
    with pytest.raises(ValidationError):
        Segment(start=5.0, end=4.0, text="x")


def test_negative_start_rejected():
    with pytest.raises(ValidationError):
        Segment(start=-1.0, end=1.0, text="x")


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_text_rejected(text):
    with pytest.raises(ValidationError):
        Segment(start=0, end=1, text=text)
