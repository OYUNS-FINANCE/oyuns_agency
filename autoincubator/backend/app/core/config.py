import uuid
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_MODEL = "claude-sonnet-5-5"
CHEAP_MODEL = "claude-haiku-5-5"
STRONG_MODEL = "claude-opus-5-5"


class RubricWeights(BaseSettings):
    """Composite-score weights for the Skeptic rubric. Normalised at use, so any scale works."""

    model_config = SettingsConfigDict(
        env_prefix="RUBRIC_WEIGHT_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cac_risk: float = Field(default=1.0, ge=0)
    channel_dependency: float = Field(default=1.0, ge=0)
    churn_risk: float = Field(default=1.0, ge=0)
    defensibility: float = Field(default=1.0, ge=0)
    regulatory_risk: float = Field(default=1.0, ge=0)
    time_to_first_revenue: float = Field(default=1.0, ge=0)
    solo_founder_feasibility: float = Field(default=1.0, ge=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    database_url: str = (
        "postgresql+asyncpg://autoincubator:autoincubator@localhost:5432/autoincubator"
    )
    redis_url: str = "redis://localhost:6379/0"
    arq_queue_name: str = "arq:queue"
    default_user_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
    """Owner of every row until auth exists (single-user mode)."""

    # Providers
    llm_provider: Literal["anthropic", "fake"] = "fake"
    search_provider: Literal["mock", "tavily", "serper"] = "mock"
    anthropic_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    serper_api_key: SecretStr | None = None
    # Per-agent model routing (ADR 0008): cheap model for the high-volume Scout, the strongest
    # for the two judgement-heavy agents. Every one can be overridden from the environment.
    scout_model: str = CHEAP_MODEL
    analyst_model: str = DEFAULT_MODEL
    skeptic_model: str = STRONG_MODEL
    product_architect_model: str = DEFAULT_MODEL
    gtm_strategist_model: str = DEFAULT_MODEL
    financial_modeler_model: str = DEFAULT_MODEL
    editor_model: str = STRONG_MODEL
    llm_prompt_caching: bool = True
    """Mark system prompts (and the first user turn on a retry) as cacheable."""
    llm_max_validation_retries: int = Field(default=2, ge=0)
    fake_llm_latency_ms: int = Field(default=0, ge=0)
    """Artificial delay per FakeLLM call: makes offline runs observable live (UI, kill tests)."""

    # Phase-1 graph
    quality_threshold: float = Field(default=6.0, ge=1, le=10)
    max_scout_iterations: int = Field(default=2, ge=1)
    min_viable_ideas: int = Field(default=3, ge=1)
    max_briefs: int = Field(default=5, ge=1)
    scout_target_candidates: int = Field(default=10, ge=1)
    dedup_threshold: float = Field(default=0.6, gt=0, le=1)
    agent_concurrency: int = Field(default=4, ge=1)
    rubric_weights: RubricWeights = Field(default_factory=RubricWeights)

    # Runs: budget, worker leases, streaming
    run_max_tokens: int = Field(default=2_000_000, ge=1)
    """Per-run cap on LLM tokens (input + output + cache). A request may only lower it."""
    run_max_searches: int = Field(default=300, ge=1)
    """Per-run cap on search-provider calls (cache hits are free)."""
    run_job_timeout_s: int = Field(default=3_600, ge=10)
    run_lease_ttl_s: float = Field(default=60.0, gt=0)
    """A run whose worker stops renewing its lease for this long is recovered by another."""
    sse_poll_interval_s: float = Field(default=5.0, gt=0)
    """Fallback DB poll for SSE streams, in case a NOTIFY is missed."""

    daily_cost_cap_usd: float = Field(default=25.0, ge=0)
    """Global cap on LLM spend per UTC day, across all runs. 0 disables it. At the cap new runs
    are refused and the next LLM call of every running run stops it (ADR 0008)."""

    # Search (ADR 0008)
    search_timeout_s: float = Field(default=15.0, gt=0)
    search_max_retries: int = Field(default=3, ge=0)
    search_rate_per_s: float = Field(default=5.0, gt=0)
    """Provider calls per second, per process (token bucket)."""
    search_cache_ttl_s: int = Field(default=86_400, ge=0)
    """Cross-run cache of provider answers; 0 disables it."""
    search_snippet_max_chars: int = Field(default=1_200, ge=100)
    search_title_max_chars: int = Field(default=200, ge=20)
    page_fetch_timeout_s: float = Field(default=20.0, gt=0)
    page_fetch_max_bytes: int = Field(default=2_000_000, ge=1_000)

    # Rate limiting of public endpoints (ADR 0008)
    rate_limit_enabled: bool = True
    rate_limit_runs_per_hour: int = Field(default=10, ge=1)
    """POST /runs per client."""
    rate_limit_llm_per_minute: int = Field(default=20, ge=1)
    """Endpoints that start LLM work on a run: co-working chat/re-score/merge, select."""
    rate_limit_api_per_minute: int = Field(default=300, ge=1)
    """Every other endpoint except the SSE stream and the health checks."""
    trusted_proxy_hops: int = Field(default=0, ge=0)
    """Reverse proxies in front of the API that append to X-Forwarded-For. 0 = use the socket
    peer address and ignore the header."""

    # Observability (ADR 0008)
    otel_exporter_otlp_endpoint: str | None = None
    sentry_dsn: str | None = None  # unset = error reporting off (ADR 0009)
    """OTLP/HTTP base URL, e.g. http://jaeger:4318. Unset = tracing off."""
    otel_service_name: str = "autoincubator"

    # Co-working (ADR 0006)
    cowork_reply_timeout_s: float = Field(default=300.0, gt=0)
    """A chat reply still pending after this long is reported as failed."""
    rejected_reasons_max: int = Field(default=20, ge=1)
    """How many recent rejection reasons the founder profile keeps for Mode B."""

    @property
    def asyncpg_dsn(self) -> str:
        """Plain asyncpg DSN (no SQLAlchemy driver suffix), for LISTEN connections."""
        return self.checkpoint_database_url

    @property
    def checkpoint_database_url(self) -> str:
        """psycopg-style URL for the LangGraph checkpointer (no SQLAlchemy driver suffix)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
