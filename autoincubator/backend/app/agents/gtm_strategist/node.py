"""GTM Strategist node: positioning, ICP, channels ranked by CAC, first-100-customers plan."""

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
from app.agents.gtm_strategist import prompts
from app.agents.gtm_strategist.schemas import GtmPlan
from app.events.schema import AgentCompleted, AgentStarted
from app.graph.deps import GraphDeps
from app.graph.state import Phase1State
from app.services.plan_trace import gtm_registry, known_brief_numbers

AGENT = "gtm_strategist"
_NAMES = frozenset({"name", "step", "channel"})


async def gtm_strategist_node(state: Phase1State, runtime: Runtime[GraphDeps]) -> Phase1State:
    deps = runtime.context
    brief = selected_brief(state)
    started = time.monotonic()
    await deps.events.emit(AgentStarted(node=AGENT, items=1), agent=AGENT)
    known, allowed = known_brief_numbers(brief), brief_urls(brief)

    def check(out: GtmPlan) -> None:
        check_sources((c.expected_cac for c in out.channels), allowed)
        check_numbers(out, known.extend(gtm_registry(out)), _NAMES)

    result = await generate_section(
        deps,
        agent=AGENT,
        model=deps.settings.gtm_strategist_model,
        system=prompts.SYSTEM_V1,
        content=render_plan_context(state["run_input"], brief),
        output_type=GtmPlan,
        check=check,
    )
    plan = result.output
    await deps.events.emit(
        AgentCompleted(
            node=AGENT,
            duration_ms=elapsed_ms(started),
            summary={"channels": len(plan.channels), "tactics": len(plan.zero_budget_tactics)},
        ),
        agent=AGENT,
    )
    return {"gtm": plan, "usage": result.usage}
