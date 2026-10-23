"""The human-in-the-loop checkpoint: pause with the ranked briefs, resume with a selection."""

from __future__ import annotations

from typing import Any

import structlog
from langgraph.types import interrupt
from pydantic import ValidationError

from app.agents.common.brief import CheckpointPayload, ResumePayload
from app.graph.state import Phase1State

log = structlog.get_logger(__name__)


def checkpoint_payload(state: Phase1State, error: str | None = None) -> CheckpointPayload:
    return CheckpointPayload(
        briefs=state.get("briefs", []),
        viable_count=state.get("viable_count", 0),
        shortfall=state.get("shortfall"),
        iterations=state.get("iteration", 0),
        error=error,
    )


def _selection_error(resume: Any) -> str | None:
    try:
        ResumePayload.model_validate(resume)
    except ValidationError as exc:
        return f"invalid resume payload: {exc.errors(include_url=False)}"
    return None


def checkpoint_node(state: Phase1State) -> Phase1State:
    """Pauses until a valid selection arrives.

    The node re-runs from the top on every resume, and LangGraph replays earlier resume
    values to earlier interrupt() calls in order. An invalid answer therefore cannot be
    "retried" by raising (the bad value would be replayed forever); instead the node asks
    again with a further interrupt() carrying the error. Everything here is side-effect free.

    The selection is any idea from the application tables (ADR 0006): co-working may have
    edited or merged ideas since the snapshot, so the payload brings the brief itself.
    """
    resume = interrupt(checkpoint_payload(state).model_dump(mode="json"))
    while (error := _selection_error(resume)) is not None:
        log.warning("checkpoint.invalid_selection", error=error)
        resume = interrupt(checkpoint_payload(state, error).model_dump(mode="json"))
    selection = ResumePayload.model_validate(resume)
    log.info("checkpoint.resumed", selected_idea_id=selection.idea_id, key=selection.brief.idea_id)
    return {"selected_idea_id": selection.idea_id, "selected_brief": selection.brief}
