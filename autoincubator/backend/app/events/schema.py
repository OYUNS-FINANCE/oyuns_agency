"""Typed run events (SPEC §6). See ADR 0003.

An event's *data* model (e.g. `AgentStarted`) is what producers emit. The persisted and
streamed form is the envelope `{id, run_id, ts, agent, type, data}`: the `Event` union,
discriminated on `type`, which is what SSE clients receive as JSON.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.db.enums import RunStatus


class EventData(BaseModel):
    event_type: ClassVar[str]


# --- Run lifecycle ----------------------------------------------------------------------


class RunStatusChanged(EventData):
    event_type: ClassVar[str] = "run.status"
    status: RunStatus
    previous: RunStatus | None = None
    detail: str | None = None


class RunInterrupted(EventData):
    event_type: ClassVar[str] = "run.interrupted"
    viable_count: int
    shortfall: str | None = None
    idea_ids: list[uuid.UUID]


class RunResumed(EventData):
    event_type: ClassVar[str] = "run.resumed"
    selected_idea_id: uuid.UUID | None = None


class RunCompleted(EventData):
    event_type: ClassVar[str] = "run.completed"


class RunErrored(EventData):
    event_type: ClassVar[str] = "run.error"
    code: str
    message: str


# --- Agents -----------------------------------------------------------------------------


class AgentStarted(EventData):
    event_type: ClassVar[str] = "agent.started"
    node: str
    iteration: int | None = None
    items: int | None = Field(default=None, description="Ideas this node will work on.")


class AgentThought(EventData):
    """A short progress note written by the node itself (not model reasoning)."""

    event_type: ClassVar[str] = "agent.thought"
    text: str


class AgentToolCall(EventData):
    event_type: ClassVar[str] = "agent.tool_call"
    tool: Literal["search"]
    query: str
    result_count: int
    idea_key: str | None = None


class AgentCompleted(EventData):
    event_type: ClassVar[str] = "agent.completed"
    node: str
    duration_ms: int
    summary: dict[str, int] = Field(default_factory=dict)


# --- Ideas ------------------------------------------------------------------------------


class IdeaCreated(EventData):
    event_type: ClassVar[str] = "idea.created"
    idea_id: uuid.UUID
    key: str
    title: str
    rank: int | None
    composite_score: float | None
    version: int


class IdeaUpdated(EventData):
    event_type: ClassVar[str] = "idea.updated"
    idea_id: uuid.UUID
    version: int
    composite_score: float | None = None


# --- Budget -----------------------------------------------------------------------------

BudgetKind = Literal["tokens", "searches"]


class BudgetWarning(EventData):
    event_type: ClassVar[str] = "budget.warning"
    kind: BudgetKind
    used: int
    limit: int


class BudgetExhausted(EventData):
    event_type: ClassVar[str] = "budget.exhausted"
    kind: BudgetKind
    used: int
    limit: int


# --- Envelopes --------------------------------------------------------------------------


class EventEnvelope(BaseModel):
    id: int
    run_id: uuid.UUID
    ts: datetime
    agent: str | None = None


class RunStatusEvent(EventEnvelope):
    type: Literal["run.status"]
    data: RunStatusChanged


class RunInterruptedEvent(EventEnvelope):
    type: Literal["run.interrupted"]
    data: RunInterrupted


class RunResumedEvent(EventEnvelope):
    type: Literal["run.resumed"]
    data: RunResumed


class RunCompletedEvent(EventEnvelope):
    type: Literal["run.completed"]
    data: RunCompleted


class RunErrorEvent(EventEnvelope):
    type: Literal["run.error"]
    data: RunErrored


class AgentStartedEvent(EventEnvelope):
    type: Literal["agent.started"]
    data: AgentStarted


class AgentThoughtEvent(EventEnvelope):
    type: Literal["agent.thought"]
    data: AgentThought


class AgentToolCallEvent(EventEnvelope):
    type: Literal["agent.tool_call"]
    data: AgentToolCall


class AgentCompletedEvent(EventEnvelope):
    type: Literal["agent.completed"]
    data: AgentCompleted


class IdeaCreatedEvent(EventEnvelope):
    type: Literal["idea.created"]
    data: IdeaCreated


class IdeaUpdatedEvent(EventEnvelope):
    type: Literal["idea.updated"]
    data: IdeaUpdated


class BudgetWarningEvent(EventEnvelope):
    type: Literal["budget.warning"]
    data: BudgetWarning


class BudgetExhaustedEvent(EventEnvelope):
    type: Literal["budget.exhausted"]
    data: BudgetExhausted


Event = Annotated[
    RunStatusEvent
    | RunInterruptedEvent
    | RunResumedEvent
    | RunCompletedEvent
    | RunErrorEvent
    | AgentStartedEvent
    | AgentThoughtEvent
    | AgentToolCallEvent
    | AgentCompletedEvent
    | IdeaCreatedEvent
    | IdeaUpdatedEvent
    | BudgetWarningEvent
    | BudgetExhaustedEvent,
    Field(discriminator="type"),
]
EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)

EVENT_TYPES: frozenset[str] = frozenset(
    cls.event_type
    for cls in (
        RunStatusChanged,
        RunInterrupted,
        RunResumed,
        RunCompleted,
        RunErrored,
        AgentStarted,
        AgentThought,
        AgentToolCall,
        AgentCompleted,
        IdeaCreated,
        IdeaUpdated,
        BudgetWarning,
        BudgetExhausted,
    )
)
