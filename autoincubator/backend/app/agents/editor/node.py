"""Editor node (fan-in): code consistency checks, an LLM review, the assembled BusinessPlan."""

from __future__ import annotations

import json
import time

from langgraph.runtime import Runtime

from app.agents.common.context import elapsed_ms
from app.agents.common.phase2 import (
    check_numbers,
    generate_section,
    render_plan_context,
    selected_brief,
)
from app.agents.editor import prompts
from app.agents.editor.schemas import BusinessPlan, Contradiction, EditorOutput
from app.events.schema import AgentCompleted, AgentStarted
from app.graph.deps import GraphDeps
from app.graph.state import Phase1State
from app.services import plan_format as fmt
from app.services.finance import FinancialModel
from app.services.plan_checks import run_checks
from app.services.plan_trace import (
    assumption_registry,
    contradiction_registry,
    financial_registry,
    gtm_registry,
    known_brief_numbers,
    product_registry,
)

AGENT = "editor"


def key_figures(model: FinancialModel) -> str:
    lines = []
    for s in model.scenarios.values():
        ue, last = s.unit_economics, s.months[-1]
        lines.append(
            f"- {s.scenario}: ARPA {fmt.money(ue.arpa)}, gross margin "
            f"{fmt.pct(ue.gross_margin_pct)}, blended CAC {fmt.money(ue.blended_cac)}, "
            f"LTV {fmt.money(ue.ltv)}, LTV:CAC {fmt.ratio(ue.ltv_to_cac)}, payback "
            f"{fmt.num(ue.payback_months)} months, month-12 MRR {fmt.money(last.mrr)}, "
            f"month-12 cash {fmt.money(last.cash)}, break-even "
            f"{fmt.month(s.break_even_month)}, cash runs out {fmt.month(s.cash_out_month)}"
        )
    return "\n".join(lines)


def _checks_text(checks: list[Contradiction]) -> str:
    return "\n".join(f"- [{c.code}] {c.description}" for c in checks) or "- none"


async def editor_node(state: Phase1State, runtime: Runtime[GraphDeps]) -> Phase1State:
    deps = runtime.context
    brief = selected_brief(state)
    product, gtm = state["product"], state["gtm"]
    assumptions, financials = state["assumptions"], state["financials"]
    started = time.monotonic()
    await deps.events.emit(AgentStarted(node=AGENT, items=1), agent=AGENT)

    checks = run_checks(brief, product, gtm, assumptions, state["run_input"])
    known = (
        known_brief_numbers(brief)
        .extend(product_registry(product))
        .extend(gtm_registry(gtm))
        .extend(assumption_registry(assumptions))
        .extend(financial_registry(financials))
        .extend(contradiction_registry(checks))
    )
    sections = {
        "product_architect": product.model_dump(mode="json"),
        "gtm_strategist": gtm.model_dump(mode="json"),
        "financial_assumptions": assumptions.model_dump(mode="json"),
    }
    content = (
        f"{render_plan_context(state['run_input'], brief)}\n\n"
        f"Specialist sections:\n{json.dumps(sections, indent=1, ensure_ascii=False)}\n\n"
        f"Key figures computed by the engine:\n{key_figures(financials)}\n\n"
        f"Automated consistency checks that failed:\n{_checks_text(checks)}"
    )

    def check(out: EditorOutput) -> None:
        check_numbers(out, known, frozenset())

    result = await generate_section(
        deps,
        agent=AGENT,
        model=deps.settings.editor_model,
        system=prompts.SYSTEM_V1,
        content=content,
        output_type=EditorOutput,
        check=check,
    )
    out = result.output
    contradictions = checks + [
        Contradiction(code="editor_review", origin="editor", **c.model_dump())
        for c in out.contradictions
    ]
    selected_id = state.get("selected_idea_id")
    plan = BusinessPlan(
        idea_id=selected_id or brief.idea_id,
        brief=brief,
        executive_summary=out.executive_summary,
        product=product,
        gtm=gtm,
        assumptions=assumptions,
        financials=financials,
        contradictions=contradictions,
        risks=out.risks,
        checklist=out.checklist,
    )
    await deps.events.emit(
        AgentCompleted(
            node=AGENT,
            duration_ms=elapsed_ms(started),
            summary={
                "contradictions": len(contradictions),
                "failed_checks": len(checks),
                "risks": len(out.risks),
            },
        ),
        agent=AGENT,
    )
    return {"plan": plan, "usage": result.usage}
