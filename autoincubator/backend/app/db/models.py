"""Application tables. LangGraph's checkpoint tables are not modelled here (ADR 0002)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.enums import (
    CoworkAgent,
    CoworkMessageState,
    CoworkRole,
    IdeaStatus,
    IdeaVersionSource,
    RiskTolerance,
    RunMode,
    RunStatus,
)


def _enum[E: StrEnum](cls: type[E], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _user_id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), index=True)


def _run_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"))


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_user_id_created_at", "user_id", text("created_at DESC")),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[RunMode] = mapped_column(_enum(RunMode, "run_mode"))
    seed: Mapped[str | None] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    """RunInput snapshot, including the founder profile for Mode B."""
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus, "run_status"), index=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    max_tokens: Mapped[int] = mapped_column(BigInteger)
    max_searches: Mapped[int] = mapped_column(Integer)
    tokens_used: Mapped[int] = mapped_column(BigInteger, server_default="0")
    searches_used: Mapped[int] = mapped_column(Integer, server_default="0")
    viable_count: Mapped[int | None] = mapped_column(Integer)
    shortfall: Mapped[str | None] = mapped_column(Text)
    selected_idea_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    """The idea chosen at the checkpoint (ADR 0006). No FK: ideas already reference runs."""
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Idea(Base):
    __tablename__ = "ideas"
    __table_args__ = (UniqueConstraint("run_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = _user_id()
    key: Mapped[str] = mapped_column(String(40))
    """Graph-level id (`opp-01`); the value the checkpoint's resume payload refers to."""
    status: Mapped[IdeaStatus] = mapped_column(_enum(IdeaStatus, "idea_status"))
    rank: Mapped[int | None] = mapped_column(Integer)
    composite_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    current_version: Mapped[int] = mapped_column(Integer)
    merged_from: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    """Ids of the ideas a merged hybrid was made from."""
    reject_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IdeaVersion(Base):
    __tablename__ = "idea_versions"
    __table_args__ = (UniqueConstraint("idea_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    idea_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ideas.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = _user_id()
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[IdeaVersionSource] = mapped_column(
        _enum(IdeaVersionSource, "idea_version_source")
    )
    opportunity: Mapped[dict[str, Any]] = mapped_column(JSONB)
    analysis: Mapped[dict[str, Any]] = mapped_column(JSONB)
    critique: Mapped[dict[str, Any]] = mapped_column(JSONB)
    composite_score: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    patch: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    """The JSON Patch that produced a `cowork` version from its predecessor."""
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cowork_messages.id", ondelete="SET NULL"), unique=True
    )
    """The chat message whose proposal was applied; unique, so a proposal applies once."""
    created_at: Mapped[datetime] = _now()


class CoworkMessage(Base):
    __tablename__ = "cowork_messages"
    __table_args__ = (Index("ix_cowork_messages_idea_id_created_at", "idea_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    idea_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ideas.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = _user_id()
    agent: Mapped[CoworkAgent] = mapped_column(_enum(CoworkAgent, "cowork_agent"))
    role: Mapped[CoworkRole] = mapped_column(_enum(CoworkRole, "cowork_role"))
    state: Mapped[CoworkMessageState] = mapped_column(
        _enum(CoworkMessageState, "cowork_message_state")
    )
    content: Mapped[str] = mapped_column(Text)
    proposed_patch: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    """RFC 6902 operations against the idea brief, proposed by the agent."""
    based_on_version: Mapped[int] = mapped_column(Integer)
    """The idea version the conversation saw when this message was written."""
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class AgentEventRow(Base):
    __tablename__ = "agent_events"
    __table_args__ = (Index("ix_agent_events_run_id_id", "run_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    user_id: Mapped[uuid.UUID] = _user_id()
    type: Mapped[str] = mapped_column(String(40))
    """Not a Postgres enum: later phases add event types without a type migration."""
    agent: Mapped[str | None] = mapped_column(String(40))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class SearchCacheEntry(Base):
    __tablename__ = "search_cache"
    __table_args__ = (UniqueConstraint("run_id", "query_norm", "max_results"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    user_id: Mapped[uuid.UUID] = _user_id()
    query_norm: Mapped[str] = mapped_column(Text)
    max_results: Mapped[int] = mapped_column(Integer)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class RunCost(Base):
    __tablename__ = "run_costs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = _user_id()
    agent: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cache_read_input_tokens: Mapped[int] = mapped_column(Integer)
    cache_creation_input_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    attempt: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now()


class FounderProfileRow(Base):
    __tablename__ = "founder_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    skills: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    region: Mapped[str | None] = mapped_column(String(120))
    capital_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    risk_tolerance: Mapped[RiskTolerance] = mapped_column(_enum(RiskTolerance, "risk_tolerance"))
    weekly_hours: Mapped[int | None] = mapped_column(Integer)
    rejected_idea_reasons: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
