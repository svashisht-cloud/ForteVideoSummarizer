"""Unit tests for llm.py: provider adapters with the SDKs faked (no network)."""

import logging
from types import SimpleNamespace

import anthropic
import httpx2
import openai
import pytest

from app.pipeline import llm as llm_mod
from app.pipeline.errors import PipelineError
from app.pipeline.llm import AnthropicLLM, OpenAILLM, TokenCount, check_key, make_llm
from app.pipeline.models import ChunkPoints, LLMPoint

KEY = "sk-ant-test-secret-1234"
REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def anthropic_error(cls, status, message="boom"):
    return cls(message, response=httpx2.Response(status, request=REQ), body=None)


# --- fake Anthropic SDK ------------------------------------------------------------


class FakeStream:
    def __init__(self, owner, kwargs):
        self.owner, self.kwargs = owner, kwargs

    async def __aenter__(self):
        if self.owner.error:
            raise self.owner.error
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self.owner.message


class FakeMessages:
    def __init__(self, owner):
        self.owner = owner

    def stream(self, **kwargs):
        self.owner.calls.append(kwargs)
        return FakeStream(self.owner, kwargs)


class FakeModels:
    def __init__(self, owner):
        self.owner = owner

    async def list(self, **kwargs):
        if self.owner.error:
            raise self.owner.error
        return SimpleNamespace(data=[])


class FakeAnthropic:
    def __init__(self, parsed=None, stop_reason="end_turn", usage=None, error=None):
        self.calls = []
        self.error = error
        self.closed = False
        self.message = SimpleNamespace(
            stop_reason=stop_reason,
            parsed_output=parsed,
            usage=usage
            or SimpleNamespace(
                input_tokens=100, cache_read_input_tokens=40, cache_creation_input_tokens=10, output_tokens=25
            ),
        )
        self.messages = FakeMessages(self)
        self.models = FakeModels(self)

    async def close(self):
        self.closed = True


POINTS = ChunkPoints(points=[LLMPoint(ts="0:30", text="A point.")])


# --- adapter selection ---------------------------------------------------------------


def test_make_llm_picks_the_provider_from_the_model():
    assert isinstance(make_llm("claude-opus-5-5", api_key=KEY), AnthropicLLM)
    assert isinstance(make_llm("gpt-6.1-terra", api_key="sk-x"), OpenAILLM)
    assert make_llm("claude-haiku-5-5", api_key=KEY).provider == "anthropic"


def test_make_llm_unknown_model_defaults_to_openai():
    assert isinstance(make_llm("some-custom-model", api_key="sk-x"), OpenAILLM)


# --- AnthropicLLM --------------------------------------------------------------------


@pytest.mark.anyio
async def test_anthropic_request_shape_and_result():
    fake = FakeAnthropic(parsed=POINTS)
    llm = AnthropicLLM("claude-opus-5-5", client=fake)
    parsed, counts = await llm.structured("Be brief.", "[0:30] hello", ChunkPoints, "chunk 1/2")
    assert parsed == POINTS
    # input counts cached and cache-written tokens too, like OpenAI's input_tokens
    assert counts == TokenCount(input_tokens=150, cached_input_tokens=40, output_tokens=25)
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["system"] == "Be brief."
    assert call["messages"] == [{"role": "user", "content": "[0:30] hello"}]
    assert call["output_format"] is ChunkPoints
    assert call["output_config"] == {"effort": "medium"}
    assert call["max_tokens"] >= 16000
    assert "thinking" not in call  # can't be disabled on Opus 5.5; effort controls depth


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stop_reason", "match"),
    [("refusal", "declined"), ("max_tokens", "too long")],
)
async def test_anthropic_unusable_stop_reasons(stop_reason, match):
    llm = AnthropicLLM("claude-sonnet-5-5", client=FakeAnthropic(parsed=None, stop_reason=stop_reason))
    with pytest.raises(PipelineError, match=match):
        await llm.structured("x", "y", ChunkPoints, "merge")


@pytest.mark.anyio
async def test_anthropic_missing_parsed_output_is_an_error():
    llm = AnthropicLLM("claude-opus-5-5", client=FakeAnthropic(parsed=None))
    with pytest.raises(PipelineError, match="no structured output for merge"):
        await llm.structured("x", "y", ChunkPoints, "merge")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (anthropic_error(anthropic.AuthenticationError, 401, f"invalid x-api-key {KEY}"), "Your Claude API key was rejected"),
        (anthropic_error(anthropic.PermissionDeniedError, 403), "isn't allowed to use claude-opus-5-5"),
        (anthropic_error(anthropic.NotFoundError, 404), "doesn't have access to claude-opus-5-5"),
        (anthropic_error(anthropic.RateLimitError, 429), "rate limit"),
        (anthropic_error(anthropic.BadRequestError, 400, "Your credit balance is too low"), "out of credit"),
    ],
)
async def test_anthropic_errors_are_readable_and_hide_the_key(error, expected):
    llm = AnthropicLLM("claude-opus-5-5", client=FakeAnthropic(error=error))
    with pytest.raises(PipelineError) as exc:
        await llm.structured("x", "y", ChunkPoints, "summary")
    assert expected in str(exc.value)
    assert KEY not in str(exc.value)


@pytest.mark.anyio
async def test_anthropic_close():
    fake = FakeAnthropic(parsed=POINTS)
    await AnthropicLLM("claude-opus-5-5", client=fake).aclose()
    assert fake.closed


# --- OpenAILLM (details are covered through summarize's tests) ---------------------


@pytest.mark.anyio
async def test_openai_auth_error_mentions_openai():
    class Responses:
        def stream(self, **kw):
            raise openai.AuthenticationError(
                "Incorrect API key provided: sk-abc", response=httpx2.Response(401, request=REQ), body=None
            )

    llm = OpenAILLM("gpt-6.1-terra", client=SimpleNamespace(responses=Responses()))
    with pytest.raises(PipelineError, match="Your OpenAI API key was rejected"):
        await llm.structured("x", "y", ChunkPoints, "summary")


# --- key check -----------------------------------------------------------------------


@pytest.mark.anyio
async def test_check_key_ok_and_rejected(monkeypatch, caplog):
    good, bad = FakeAnthropic(), FakeAnthropic(error=anthropic_error(anthropic.AuthenticationError, 401))
    clients = iter([good, bad])
    monkeypatch.setattr(llm_mod, "_anthropic_client", lambda api_key: next(clients))
    with caplog.at_level(logging.DEBUG):
        assert await check_key("anthropic", KEY) is None
        assert "Your Claude API key was rejected" in await check_key("anthropic", KEY)
    assert good.closed and bad.closed
    assert KEY not in caplog.text


@pytest.mark.anyio
async def test_check_key_unknown_provider():
    with pytest.raises(ValueError):
        await check_key("gemini", "k")
