from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Segment(BaseModel):
    """A span of transcript text. Times are in seconds."""

    start: float = Field(ge=0)
    end: float
    text: str

    @field_validator("text")
    @classmethod
    def _text_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text must not be empty")
        return v

    @model_validator(mode="after")
    def _end_after_start(self) -> "Segment":
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) must be >= start ({self.start})")
        return self


# --- LLM-facing (structured outputs). Timestamps are the exact "m:ss" marker
# strings from the prompt; code parses and snaps them. No defaults or field
# constraints, to stay compatible with strict JSON schemas.


class LLMPoint(BaseModel):
    ts: str
    text: str


class ChunkPoints(BaseModel):
    points: list[LLMPoint]


class LLMSection(BaseModel):
    title: str
    points: list[LLMPoint]


class LLMSummary(BaseModel):
    tldr: str
    sections: list[LLMSection]


# --- Final summary (seconds). ---


class Point(BaseModel):
    t: float
    text: str


class Section(BaseModel):
    title: str
    start: float
    end: float
    points: list[Point]


class Usage(BaseModel):
    """Tokens used by the LLM calls that made a summary, and the estimated cost.
    input_tokens includes cached_input_tokens; output_tokens includes reasoning."""

    model: str
    calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None  # None when the model's price isn't known


class Summary(BaseModel):
    tldr: str
    sections: list[Section]
    usage: Usage | None = None  # None for summaries cached before usage was tracked, and for free ones
    # "ai": written by the LLM. "extractive": free key moments quoted from the captions (extract.py).
    method: Literal["ai", "extractive"] = "ai"


# --- Video metadata (yt-dlp, no download). ---


class Chapter(BaseModel):
    title: str
    start: float
    end: float | None = None


class VideoMetadata(BaseModel):
    title: str | None = None
    language: str | None = None  # original spoken language, e.g. "en-US"
    chapters: list[Chapter] = []
