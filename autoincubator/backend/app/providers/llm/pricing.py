"""Per-model token prices (USD per million tokens), Anthropic first-party rates.

Input/output/cache-read rates are the published ones (2026-10). Cache writes are priced at
1.25x input (5-minute TTL); prompt caching is not enabled yet, so they are normally zero.
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
}


def cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> float:
    """Cost of one call. Unknown models cost 0.0 (logged by the caller as unpriced)."""
    price = PRICES.get(model)
    if price is None:
        return 0.0
    return (
        input_tokens * price.input_per_mtok
        + output_tokens * price.output_per_mtok
        + cache_read_input_tokens * price.cache_read_per_mtok
        + cache_creation_input_tokens * price.cache_write_per_mtok
    ) / 1_000_000
