"""Per-model token prices (USD per million tokens), first-party rates.

Input/output/cache-read rates are the published ones (2026-10). Cache writes are priced at
1.25x input (5-minute TTL), the TTL `LLM_PROMPT_CACHING` uses.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_per_mtok: float


PRICES: dict[str, ModelPrice] = {
    "claude-opus-5-5": ModelPrice(4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": ModelPrice(2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": ModelPrice(0.10, 0.50, 0.01, 0.125),
    # OpenAI: caching is automatic and writes are not billed separately. Dated snapshots
    # (gpt-5-2025-08-07) are priced by prefix in cost_usd.
    "gpt-5": ModelPrice(1.25, 10.00, 0.125, 1.25),
    "gpt-5-mini": ModelPrice(0.25, 2.00, 0.025, 0.25),
    "gpt-5-nano": ModelPrice(0.05, 0.40, 0.005, 0.05),
}


def price_for(model: str) -> ModelPrice | None:
    """Exact match, else the longest listed prefix (dated snapshots like gpt-5-mini-2025-08-07)."""
    if model in PRICES:
        return PRICES[model]
    prefixes = [name for name in PRICES if model.startswith(name + "-")]
    return PRICES[max(prefixes, key=len)] if prefixes else None


def cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> float:
    """Cost of one call. Unknown models cost 0.0 (logged by the caller as unpriced)."""
    price = price_for(model)
    if price is None:
        return 0.0
    return (
        input_tokens * price.input_per_mtok
        + output_tokens * price.output_per_mtok
        + cache_read_input_tokens * price.cache_read_per_mtok
        + cache_creation_input_tokens * price.cache_write_per_mtok
    ) / 1_000_000
