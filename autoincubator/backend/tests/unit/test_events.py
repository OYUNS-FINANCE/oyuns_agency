"""The event union: every producer-side type has an envelope, and envelopes round-trip."""

import uuid
from datetime import UTC, datetime
from typing import get_args

import pytest
from pydantic import ValidationError

from app.db.enums import RunStatus
from app.events import schema as s
from app.events.schema import EVENT_ADAPTER, EVENT_TYPES

SAMPLES: list[s.EventData] = [
    s.RunStatusChanged(status=RunStatus.RUNNING, previous=RunStatus.QUEUED),
    s.RunInterrupted(viable_count=3, idea_ids=[uuid.uuid4()]),
    s.RunResumed(),
    s.RunCompleted(),
    s.RunErrored(code="run_failed", message="boom"),
    s.AgentStarted(node="scout", iteration=1),
    s.AgentThought(text="Planned 6 searches."),
    s.AgentToolCall(tool="search", query="dental", result_count=3),
    s.AgentCompleted(node="scout", duration_ms=12, summary={"kept": 4}),
    s.IdeaCreated(
        idea_id=uuid.uuid4(), key="opp-01", title="T", rank=1, composite_score=7.5, version=1
    ),
    s.IdeaUpdated(idea_id=uuid.uuid4(), version=2),
    s.BudgetWarning(kind="tokens", used=80, limit=100),
    s.BudgetExhausted(kind="searches", used=10, limit=10),
]


def test_every_event_type_has_a_sample_and_an_envelope() -> None:
    assert {d.event_type for d in SAMPLES} == EVENT_TYPES
    (union, _) = get_args(s.Event)
    envelope_types = {get_args(cls.model_fields["type"].annotation)[0] for cls in get_args(union)}
    assert envelope_types == EVENT_TYPES


@pytest.mark.parametrize("data", SAMPLES, ids=lambda d: d.event_type)
def test_envelope_round_trip(data: s.EventData) -> None:
    raw = {
        "id": 7,
        "run_id": str(uuid.uuid4()),
        "ts": datetime.now(UTC).isoformat(),
        "agent": "scout",
        "type": data.event_type,
        "data": data.model_dump(mode="json"),
    }
    event = EVENT_ADAPTER.validate_python(raw)
    assert event.type == data.event_type
    assert event.data == data
    assert EVENT_ADAPTER.validate_json(EVENT_ADAPTER.dump_json(event)) == event


def test_unknown_event_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EVENT_ADAPTER.validate_python(
            {
                "id": 1,
                "run_id": str(uuid.uuid4()),
                "ts": "2026-01-01T00:00:00Z",
                "type": "agent.dreamed",
                "data": {},
            }
        )
