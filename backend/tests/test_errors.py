"""Unit tests for errors.openai_error_message (pure)."""

import httpx2
import openai
import pytest

from app.pipeline.errors import openai_error_message

REQ = httpx2.Request("POST", "https://api.openai.com/v1/responses")


def status_error(cls, status, code=None):
    body = {"message": "boom", "type": "x", "code": code} if code else None
    return cls("boom", response=httpx2.Response(status, request=REQ), body=body)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (status_error(openai.AuthenticationError, 401, "invalid_api_key"), "Your OpenAI API key was rejected"),
        (status_error(openai.PermissionDeniedError, 403), "isn't allowed to use gpt-6-astra"),
        (status_error(openai.NotFoundError, 404, "model_not_found"), "doesn't have access to gpt-6-astra"),
        (status_error(openai.RateLimitError, 429, "insufficient_quota"), "out of credit"),
        (status_error(openai.RateLimitError, 429, "rate_limit_exceeded"), "rate limit"),
    ],
)
def test_key_and_model_errors_are_readable(error, expected):
    assert expected in openai_error_message(error, "gpt-6-astra", "summary")


def test_other_errors_keep_generic_message():
    err = openai.APIConnectionError(request=REQ)
    msg = openai_error_message(err, "gpt-6-astra", "summary")
    assert msg.startswith("OpenAI request failed for summary: APIConnectionError")


def test_message_never_contains_the_key():
    # OpenAI's 401 message echoes part of the key; we don't pass it through.
    err = openai.AuthenticationError(
        "Incorrect API key provided: sk-abc...wxyz", response=httpx2.Response(401, request=REQ), body=None
    )
    assert "sk-" not in openai_error_message(err, "m", "summary")
