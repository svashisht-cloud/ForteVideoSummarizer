"""Models the app offers and their estimated OpenAI cost.

Prices are USD per 1M tokens, standard (non-batch) rates for prompts under the
long-context threshold. Checked 2026-11-22 against third-party listings of
OpenAI's pricing; OpenAI's own page is the final word. All four IDs were
confirmed with models.list() and a structured-output call on 2026-11-22.
Update this table when prices move or models are added; a model missing here
can't be picked, and its cost shows as unknown.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    label: str
    input: float
    cached_input: float
    output: float
    cached_is_estimate: bool = False  # True: cached rate assumed to be 10% of input


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    input: float
    cached_input: float
    output: float
    cached_is_estimate: bool


# Cheapest first; this is the order of the picker.
PRICES: dict[str, Price] = {
    "gpt-6-luna": Price("GPT-6 Luna", input=0.10, cached_input=0.01, output=0.50, cached_is_estimate=True),
    "gpt-6.1-terra": Price("GPT-6.1 Terra", input=1.00, cached_input=0.05, output=5.00),
    "gpt-6.1-sol": Price("GPT-6.1 Sol", input=2.00, cached_input=0.10, output=10.00),
    "gpt-6-astra": Price("GPT-6 Astra", input=10.00, cached_input=1.00, output=50.00, cached_is_estimate=True),
}


def available_models() -> list[ModelInfo]:
    return [ModelInfo(id=k, **vars(p)) for k, p in PRICES.items()]


def is_known_model(model: str) -> bool:
    """Whether the picker offers this exact model ID."""
    return model in PRICES


def price_for(model: str) -> Price | None:
    """Price for a model ID; dated snapshots (gpt-6.1-terra-2026-10-01) use the base model's price."""
    if model in PRICES:
        return PRICES[model]
    matches = [name for name in PRICES if model.startswith(name + "-")]
    return PRICES[max(matches, key=len)] if matches else None


def cost_usd(model: str, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> float | None:
    """Estimated cost in USD, or None if the model's price isn't known.
    input_tokens includes the cached ones; output_tokens includes reasoning."""
    price = price_for(model)
    if price is None:
        return None
    cached = min(cached_input_tokens, input_tokens)
    return (
        (input_tokens - cached) * price.input + cached * price.cached_input + output_tokens * price.output
    ) / 1_000_000
