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

    # Providers
    llm_provider: Literal["anthropic", "fake"] = "fake"
    search_provider: Literal["mock"] = "mock"
    anthropic_api_key: SecretStr | None = None
    scout_model: str = DEFAULT_MODEL
    analyst_model: str = DEFAULT_MODEL
    skeptic_model: str = DEFAULT_MODEL
    llm_max_validation_retries: int = Field(default=2, ge=0)

    # Phase-1 graph
    quality_threshold: float = Field(default=6.0, ge=1, le=10)
    max_scout_iterations: int = Field(default=2, ge=1)
    min_viable_ideas: int = Field(default=3, ge=1)
    max_briefs: int = Field(default=5, ge=1)
    scout_target_candidates: int = Field(default=10, ge=1)
    dedup_threshold: float = Field(default=0.6, gt=0, le=1)
    agent_concurrency: int = Field(default=4, ge=1)
    rubric_weights: RubricWeights = Field(default_factory=RubricWeights)

    @property
    def checkpoint_database_url(self) -> str:
        """psycopg-style URL for the LangGraph checkpointer (no SQLAlchemy driver suffix)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
