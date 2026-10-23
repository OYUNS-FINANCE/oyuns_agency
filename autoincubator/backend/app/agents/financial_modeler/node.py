"""Financial Modeler node: the LLM proposes an AssumptionSet; the engine computes the model."""

from __future__ import annotations

import time

from langgraph.runtime import Runtime

from app.agents.common.context import elapsed_ms
from app.agents.common.phase2 import (
    brief_urls,
    check_numbers,
    check_sources,
    generate_section,
    render_plan_context,
    selected_brief,
)
from app.agents.financial_modeler import prompts
from app.agents.financial_modeler.schemas import AssumptionSet
from app.events.schema import AgentCompleted, AgentStarted
from app.graph.deps import GraphDeps
from app.graph.state import Phase1State
from app.services import finance
from app.services.plan_trace import assumption_registry, known_brief_numbers

AGENT = "financial_modeler"
_NAMES = frozenset({"name", "channel"})


async def financial_modeler_node(state: Phase1State, runtime: Runtime[GraphDeps]) -> Phase1State:
    deps = runtime.context
    brief = selected_brief(state)
    started = time.monotonic()
    await deps.events.emit(AgentStarted(node=AGENT, items=1), agent=AGENT)
    known, allowed = known_brief_numbers(brief), brief_urls(brief)

    def check(out: AssumptionSet) -> None:
        check_sources(out.figures(), allowed)
        check_numbers(out, known.extend(assumption_registry(out)), _NAMES)
        finance.compute(out)  # FinanceInputError (a ValueError) is fed back to the model

    result = await generate_section(
        deps,
        agent=AGENT,
        model=deps.settings.financial_modeler_model,
        system=prompts.SYSTEM_V1,
        content=render_plan_context(state["run_input"], brief),
        output_type=AssumptionSet,
        check=check,
    )
    assumptions = result.output
    model = finance.compute(assumptions)
    estimates = sum(f.is_estimate for f in assumptions.figures())
    await deps.events.emit(
        AgentCompleted(
            node=AGENT,
            duration_ms=elapsed_ms(started),
            summary={"assumptions": len(assumptions.figures()), "estimated_figures": estimates},
        ),
        agent=AGENT,
    )
    return {"assumptions": assumptions, "financials": model, "usage": result.usage}
