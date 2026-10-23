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


def _selection_error(resume: Any, valid: set[str]) -> str | None:
    try:
        selection = ResumePayload.model_validate(resume)
    except ValidationError as exc:
        return f"invalid resume payload: {exc.errors(include_url=False)}"
    if selection.selected_idea_id not in valid:
        return f"selected_idea_id {selection.selected_idea_id!r} is not one of {sorted(valid)}"
    return None


def checkpoint_node(state: Phase1State) -> Phase1State:
    """Pauses until a valid selection arrives.

    The node re-runs from the top on every resume, and LangGraph replays earlier resume
    values to earlier interrupt() calls in order. An invalid answer therefore cannot be
    "retried" by raising (the bad value would be replayed forever); instead the node asks
    again with a further interrupt() carrying the error. Everything here is side-effect free.
    """
    valid = {b.idea_id for b in state.get("briefs", [])}
    resume = interrupt(checkpoint_payload(state).model_dump(mode="json"))
    while (error := _selection_error(resume, valid)) is not None:
        log.warning("checkpoint.invalid_selection", error=error)
        resume = interrupt(checkpoint_payload(state, error).model_dump(mode="json"))
    selected = ResumePayload.model_validate(resume).selected_idea_id
    log.info("checkpoint.resumed", selected_idea_id=selected)
    return {"selected_idea_id": selected}
