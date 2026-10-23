"""Enums stored as Postgres enum types. Values are the wire format too."""

from __future__ import annotations

from enum import StrEnum


class RunMode(StrEnum):
    SEEDED = "seeded"
    AUTONOMOUS = "autonomous"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_HUMAN = "awaiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


TERMINAL_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.BUDGET_EXHAUSTED})


class IdeaStatus(StrEnum):
    ACTIVE = "active"
    REJECTED = "rejected"
    MERGED = "merged"
    SELECTED = "selected"


class IdeaVersionSource(StrEnum):
    AGENT = "agent"
    COWORK = "cowork"
    MERGE = "merge"
    RESCORE = "rescore"


class RiskTolerance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CoworkAgent(StrEnum):
    SCOUT = "scout"
    ANALYST = "analyst"
    SKEPTIC = "skeptic"


class CoworkRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class CoworkMessageState(StrEnum):
    PENDING = "pending"
    """An assistant reply that is still being generated."""
    COMPLETE = "complete"
    FAILED = "failed"
