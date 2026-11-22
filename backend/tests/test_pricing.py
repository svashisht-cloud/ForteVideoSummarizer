"""Unit tests for pricing.py (pure)."""

import pytest

from app.pipeline.pricing import available_models, cost_usd, is_known_model, price_for, provider_for


def test_known_model_cost():
    # gpt-6.1-terra: $1 / 1M input, $0.05 / 1M cached input, $5 / 1M output.
    # 1M input of which 200k cached, 100k output:
    # 800k * 1 + 200k * 0.05 + 100k * 5 (per 1M) = 0.8 + 0.01 + 0.5
    assert cost_usd("gpt-6.1-terra", input_tokens=1_000_000, cached_input_tokens=200_000, output_tokens=100_000) == pytest.approx(1.31)


def test_dated_snapshot_uses_base_price():
    assert price_for("gpt-6.1-terra-2026-10-01") == price_for("gpt-6.1-terra")


def test_unknown_model_has_no_cost():
    assert price_for("some-other-model") is None
    assert cost_usd("some-other-model", 1000, 0, 1000) is None


def test_cached_never_exceeds_input():
    # Defensive: bad counts shouldn't produce negative uncached input.
    assert cost_usd("gpt-6.1-terra", 100, 500, 0) == pytest.approx(100 * 0.05 / 1_000_000)


def test_available_models_lists_priced_models_cheapest_first():
    models = available_models()
    ids = [m.id for m in models]
    assert ids == [
        "gpt-6-luna", "gpt-6.1-terra", "gpt-6.1-sol", "gpt-6-astra",
        "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5",
    ]  # fmt: skip
    terra = models[1]
    assert (terra.label, terra.input, terra.cached_input, terra.output) == ("GPT-6.1 Terra", 1.00, 0.05, 5.00)


def test_is_known_model():
    assert is_known_model("gpt-6.1-sol")
    assert not is_known_model("gpt-6.1-sol-2026-10-01")  # picker offers exact IDs only
    assert not is_known_model("gpt-4o")


def test_provider_for():
    assert provider_for("gpt-6.1-terra") == "openai"
    assert provider_for("claude-opus-5-5") == "anthropic"
    assert provider_for("claude-something-new") == "anthropic"  # not priced, but clearly Claude
    assert provider_for("mystery") == "openai"


def test_claude_cost():
    # Opus 5.5: $4 in, $0.20 cache read, $20 out per 1M
    assert cost_usd("claude-opus-5-5", 1_000_000, 500_000, 100_000) == pytest.approx(0.5 * 4 + 0.5 * 0.2 + 0.1 * 20)
