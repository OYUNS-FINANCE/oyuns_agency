"""Conditional edges. The rank node makes the decision; routing only reads it."""

from __future__ import annotations

from typing import Literal

from app.graph.state import Phase1State


def route_after_rank(state: Phase1State) -> Literal["scout", "checkpoint"]:
    return "scout" if state.get("loop_back", False) else "checkpoint"
