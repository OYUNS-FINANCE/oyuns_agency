import uuid
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_MODEL = "claude-sonnet-5-5"


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
    search_provider: Literal["mock"] = "mock"
    anthropic_api_key: SecretStr | None = None
    scout_model: str = DEFAULT_MODEL
    analyst_model: str = DEFAULT_MODEL
    skeptic_model: str = DEFAULT_MODEL
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
