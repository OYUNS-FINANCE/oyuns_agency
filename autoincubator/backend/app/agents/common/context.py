"""Helpers shared by agent nodes."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Iterable

from app.agents.common.schemas import RunInput
from app.events.schema import AgentToolCall
from app.graph.deps import GraphDeps
from app.providers.search.base import SearchResult


def render_run_context(run_input: RunInput) -> str:
    """The founder's request, as plain text for a user message. This is trusted input."""
    c = run_input.constraints
    lines = [f"Mode: {'A (seeded)' if run_input.mode == 'seeded' else 'B (autonomous)'}"]
    if run_input.seed:
        lines.append(f"Seed: {run_input.seed}")
    lines.append("Constraints:")
    lines.append(f"- region: {c.region or 'any'}")
    lines.append(f"- business model: {c.business_model}")
    lines.append(
        f"- budget ceiling: {f'${c.budget_ceiling_usd:,.0f}' if c.budget_ceiling_usd else 'none'}"
    )
    lines.append(f"- must be feasible for a solo founder: {'yes' if c.solo_founder else 'no'}")
    lines.append(f"- excluded industries: {', '.join(c.excluded_industries) or 'none'}")
    if p := run_input.founder_profile:
        lines.append("Founder profile:")
        lines.append(f"- skills: {', '.join(p.skills) or 'unspecified'}")
        lines.append(f"- region: {p.region or 'unspecified'}")
        lines.append(
            f"- capital: {f'${p.capital_usd:,.0f}' if p.capital_usd is not None else 'unspecified'}"
        )
        lines.append(f"- risk tolerance: {p.risk_tolerance}")
        if p.rejected_idea_reasons:
            lines.append("- reasons earlier ideas were rejected:")
            lines += [f"  - {r}" for r in p.rejected_idea_reasons]
    return "\n".join(lines)


async def gather_bounded[T](aws: Iterable[Awaitable[T]], limit: int) -> list[T]:
    """Runs awaitables with at most `limit` in flight; preserves order.

    On the first failure the remaining ones are cancelled and that exception is re-raised
    as-is (not as an ExceptionGroup), so callers can catch e.g. BudgetExhaustedError.
    """
    sem = asyncio.Semaphore(limit)

    async def run(aw: Awaitable[T]) -> T:
        async with sem:
            return await aw

    try:
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(run(aw)) for aw in aws]
    except BaseExceptionGroup as group:
        raise group.exceptions[0] from None
    return [t.result() for t in tasks]


async def search_and_report(
    deps: GraphDeps, agent: str, query: str, max_results: int, idea_key: str | None = None
) -> list[SearchResult]:
    """One search, announced as an `agent.tool_call` event."""
    results = await deps.search.search(query, max_results=max_results)
    await deps.events.emit(
        AgentToolCall(tool="search", query=query, result_count=len(results), idea_key=idea_key),
        agent=agent,
    )
    return results


def elapsed_ms(started: float) -> int:
    """Milliseconds since `started` (a time.monotonic() value)."""
    return int((time.monotonic() - started) * 1000)
