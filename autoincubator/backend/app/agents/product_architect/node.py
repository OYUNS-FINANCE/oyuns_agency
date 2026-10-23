"""Product Architect node: MVP scope, architecture and a solo build estimate."""

from __future__ import annotations

import time

from langgraph.runtime import Runtime

from app.agents.common.context import elapsed_ms
from app.agents.common.phase2 import (
    check_numbers,
    generate_section,
    render_plan_context,
    selected_brief,
)
from app.agents.product_architect import prompts
from app.agents.product_architect.schemas import ProductPlan
from app.events.schema import AgentCompleted, AgentStarted
from app.graph.deps import GraphDeps
from app.graph.state import Phase1State
from app.services.plan_trace import brief_registry, product_registry

AGENT = "product_architect"
_NAMES = frozenset({"name", "choice", "layer", "fields"})


async def product_architect_node(state: Phase1State, runtime: Runtime[GraphDeps]) -> Phase1State:
    deps = runtime.context
    brief = selected_brief(state)
    started = time.monotonic()
    await deps.events.emit(AgentStarted(node=AGENT, items=1), agent=AGENT)
    known = brief_registry(brief)

    def check(out: ProductPlan) -> None:
        check_numbers(out, known.extend(product_registry(out)), _NAMES)

    result = await generate_section(
        deps,
        agent=AGENT,
        model=deps.settings.product_architect_model,
        system=prompts.SYSTEM_V1,
        content=render_plan_context(state["run_input"], brief),
        output_type=ProductPlan,
        check=check,
    )
    plan = result.output
    await deps.events.emit(
        AgentCompleted(
            node=AGENT,
            duration_ms=elapsed_ms(started),
            summary={
                "features": len(plan.features),
                "mvp_features": sum(f.scope == "now" for f in plan.features),
            },
        ),
        agent=AGENT,
    )
    return {"product": plan, "usage": result.usage}
