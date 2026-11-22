"""LLM providers behind one interface. Every summary LLM call goes through here.

Each provider has its own API shape:
- OpenAI: Responses API, streamed, `text_format=<Pydantic model>` for guaranteed JSON.
- Anthropic (Claude): Messages API, streamed, `output_format=<Pydantic model>`
  (the SDK turns it into `output_config.format` json_schema), effort "medium".

Both stream so long calls keep bytes flowing (a 60s idle connection gets cut on
some network paths). The provider is chosen from the model ID (pricing table).
"""

import logging
from dataclasses import dataclass
from typing import Literal, Protocol

import anthropic
import openai
from pydantic import BaseModel

from app.pipeline.errors import PipelineError, anthropic_error_message, openai_error_message
from app.pipeline.pricing import provider_for

log = logging.getLogger(__name__)

Provider = Literal["openai", "anthropic"]
PROVIDERS: tuple[Provider, ...] = ("openai", "anthropic")
ANTHROPIC_MAX_TOKENS = 64000  # streamed, so a large cap doesn't risk HTTP timeouts
ANTHROPIC_EFFORT = "medium"  # summarizing doesn't need deep reasoning; the Opus 5.5 default, set explicitly


@dataclass(frozen=True)
class TokenCount:
    input_tokens: int = 0  # includes cached input
    cached_input_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    provider: Provider
    model: str

    async def structured[T: BaseModel](self, instructions: str, input: str, fmt: type[T], what: str) -> tuple[T, TokenCount]:
        """One call returning `fmt`, plus its token counts. Raises PipelineError."""
        ...

    async def aclose(self) -> None: ...


class OpenAILLM:
    provider: Provider = "openai"

    def __init__(self, model: str, api_key: str | None = None, *, client=None):
        self.model = model
        self._client = client or openai.AsyncOpenAI(api_key=api_key)  # None: OPENAI_API_KEY
        self._owns_client = client is None

    async def structured[T: BaseModel](self, instructions: str, input: str, fmt: type[T], what: str) -> tuple[T, TokenCount]:
        try:
            async with self._client.responses.stream(
                model=self.model, instructions=instructions, input=input, text_format=fmt
            ) as stream:
                resp = await stream.get_final_response()
        except openai.APIError as e:
            raise PipelineError(openai_error_message(e, self.model, what)) from e
        counts = _openai_counts(resp)
        parsed = resp.output_parsed
        if parsed is None:
            raise PipelineError(f"LLM returned no structured output for {what} (refusal or empty response)")
        return parsed, counts

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.close()


def _openai_counts(resp) -> TokenCount:
    u = getattr(resp, "usage", None)
    if u is None:
        log.warning("OpenAI response had no usage; cost estimate will be low")
        return TokenCount()
    details = getattr(u, "input_tokens_details", None)
    return TokenCount(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        cached_input_tokens=getattr(details, "cached_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
    )


def _anthropic_client(api_key: str | None) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=api_key)  # None: ANTHROPIC_API_KEY


class AnthropicLLM:
    provider: Provider = "anthropic"

    def __init__(self, model: str, api_key: str | None = None, *, client=None):
        self.model = model
        self._client = client or _anthropic_client(api_key)

    async def structured[T: BaseModel](self, instructions: str, input: str, fmt: type[T], what: str) -> tuple[T, TokenCount]:
        try:
            async with self._client.messages.stream(
                model=self.model,
                max_tokens=ANTHROPIC_MAX_TOKENS,
                system=instructions,
                messages=[{"role": "user", "content": input}],
                output_format=fmt,
                output_config={"effort": ANTHROPIC_EFFORT},
            ) as stream:
                msg = await stream.get_final_message()
        except anthropic.APIError as e:
            raise PipelineError(anthropic_error_message(e, self.model, what)) from e
        counts = _anthropic_counts(msg)
        if msg.stop_reason == "refusal":
            raise PipelineError(f"Claude declined to summarize this ({what}). Try another model or video.")
        if msg.stop_reason == "max_tokens":
            raise PipelineError(f"Claude's answer for {what} was too long and got cut off.")
        parsed = getattr(msg, "parsed_output", None)
        if parsed is None:
            raise PipelineError(f"LLM returned no structured output for {what} (refusal or empty response)")
        return parsed, counts

    async def aclose(self) -> None:
        await self._client.close()


def _anthropic_counts(msg) -> TokenCount:
    u = getattr(msg, "usage", None)
    if u is None:
        return TokenCount()
    cached = getattr(u, "cache_read_input_tokens", 0) or 0
    written = getattr(u, "cache_creation_input_tokens", 0) or 0
    return TokenCount(
        input_tokens=(getattr(u, "input_tokens", 0) or 0) + cached + written,
        cached_input_tokens=cached,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
    )


def make_llm(model: str, api_key: str | None = None) -> LLM:
    """The adapter for `model`'s provider. `api_key` None: the server's env key."""
    if provider_for(model) == "anthropic":
        return AnthropicLLM(model, api_key)
    return OpenAILLM(model, api_key)


async def check_key(provider: str, api_key: str) -> str | None:
    """Validate a key with a free models.list call. None if it works, else a readable error."""
    if provider == "anthropic":
        client = _anthropic_client(api_key)
        try:
            await client.models.list(limit=1)
            return None
        except anthropic.APIError as e:
            return anthropic_error_message(e, "Claude models", "the key check")
        finally:
            await client.close()
    if provider == "openai":
        oclient = openai.AsyncOpenAI(api_key=api_key)
        try:
            await oclient.models.list()
            return None
        except openai.APIError as e:
            return openai_error_message(e, "OpenAI models", "the key check")
        finally:
            await oclient.close()
    raise ValueError(f"unknown provider {provider!r}")
