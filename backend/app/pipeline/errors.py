class PipelineError(Exception):
    """Base class for errors the pipeline reports to the user."""


class InvalidURL(PipelineError, ValueError):
    """The input is not a YouTube video URL or video ID."""


class NoCaptions(PipelineError):
    """The video has no caption tracks. Speech-to-text fallback applies."""


class CaptionsRequired(NoCaptions):
    """No captions, and the caller asked for captions only (free mode: no speech-to-text)."""


class YouTubeBlocked(PipelineError):
    """YouTube refused the request (bot detection / IP ban). Do not fall back."""


class VideoUnavailable(PipelineError):
    """The video is private, removed, age-restricted, or otherwise unplayable."""


def openai_error_message(e: Exception, model: str, what: str) -> str:
    """A readable message for an OpenAI API error. Key and model problems get
    specific advice; the raw message is left out for those because OpenAI's
    401 text echoes part of the API key."""
    import openai  # local import: errors.py stays importable without the SDK

    code = getattr(e, "code", None)
    if isinstance(e, openai.AuthenticationError):
        return "Your OpenAI API key was rejected. Check that it's correct and active."
    if isinstance(e, openai.PermissionDeniedError):
        return f"This OpenAI API key isn't allowed to use {model}."
    if isinstance(e, openai.NotFoundError) and code in (None, "model_not_found"):
        return f"This OpenAI API key doesn't have access to {model}."
    if isinstance(e, openai.RateLimitError):
        if code == "insufficient_quota":
            return "This OpenAI account is out of credit (insufficient quota). Add billing credit or use another key."
        return "OpenAI rate limit reached. Wait a moment and try again."
    return f"OpenAI request failed for {what}: {type(e).__name__}: {e}"


def anthropic_error_message(e: Exception, model: str, what: str) -> str:
    """Readable message for an Anthropic (Claude) API error; never includes the key."""
    import anthropic  # local import: errors.py stays importable without the SDK

    if isinstance(e, anthropic.AuthenticationError):
        return "Your Claude API key was rejected. Check that it's correct and active."
    if isinstance(e, anthropic.PermissionDeniedError):
        return f"This Claude API key isn't allowed to use {model}."
    if isinstance(e, anthropic.NotFoundError):
        return f"This Claude API key doesn't have access to {model}."
    if isinstance(e, anthropic.RateLimitError):
        return "Claude rate limit reached. Wait a moment and try again."
    if isinstance(e, anthropic.BadRequestError) and "credit balance" in str(e).lower():
        return "This Claude account is out of credit. Add billing credit or use another key."
    if isinstance(e, anthropic.APIStatusError):
        return f"Claude request failed for {what}: {type(e).__name__} ({e.status_code})"
    return f"Claude request failed for {what}: {type(e).__name__}"


def llm_error_message(e: Exception, provider: str, model: str, what: str) -> str:
    if provider == "anthropic":
        return anthropic_error_message(e, model, what)
    return openai_error_message(e, model, what)
