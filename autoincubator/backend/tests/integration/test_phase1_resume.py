"""Phase-1 graph on Postgres: interrupt in one process, resume the same thread in another."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig

from app.agents.analyst.schemas import MarketAnalysis
from app.agents.common.brief import IdeaBrief
from app.agents.common.schemas import RunInput
from app.agents.scout.schemas import RawOpportunity
from app.core.config import get_settings
from app.graph.builder import compile_graph
from app.graph.checkpointer import postgres_checkpointer
from app.graph.stubs import PHASE2_EDITOR, PHASE2_PARALLEL, STUB_STATUS

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[2]


def _cli(*args: str) -> dict[str, Any]:
    env = {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        "LLM_PROVIDER": "fake",
        "SEARCH_PROVIDER": "mock",
        # Unregistered types in a checkpoint would come back as dicts: fail loudly instead.
        "LANGGRAPH_STRICT_MSGPACK": "true",
    }
    proc = subprocess.run(
        [sys.executable, "scripts/run_phase1.py", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Blocked deserialization" not in proc.stderr
    result: dict[str, Any] = json.loads(proc.stdout)
    return result


async def test_interrupt_then_resume_from_a_new_process() -> None:
    thread_id = f"it-{uuid.uuid4()}"

    paused = _cli("--auto", "--thread-id", thread_id)
    assert paused["status"] == "interrupted"
    assert paused["next"] == ["checkpoint"]
    briefs = paused["checkpoint"]["briefs"]
    assert briefs, paused["checkpoint"]
    selected = briefs[0]["opportunity"]["id"]

    # A third process (this test) reads the paused state back with real model types.
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    async with postgres_checkpointer(get_settings()) as saver:
        snapshot = await compile_graph(saver).aget_state(config)
    values = snapshot.values
    assert snapshot.next == ("checkpoint",)
    assert isinstance(values["run_input"], RunInput)
    assert all(isinstance(o, RawOpportunity) for o in values["opportunities"])
    assert all(isinstance(a, MarketAnalysis) for a in values["analyses"].values())
    assert all(isinstance(b, IdeaBrief) for b in values["briefs"])

    resumed = _cli("--thread-id", thread_id, "--resume-select", selected)
    assert resumed["status"] == "completed"
    assert resumed["next"] == []
    assert resumed["selected_idea_id"] == selected
    assert resumed["phase2"] == dict.fromkeys((*PHASE2_PARALLEL, PHASE2_EDITOR), STUB_STATUS)
    # Resume did not re-run Phase-1 agents: usage is unchanged.
    assert resumed["usage"] == paused["usage"]
