"""Trend Scout, co-working: synthesise one hybrid opportunity from 2+ ideas (ADR 0006)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from app.agents.common.untrusted import neutralise_tags
from app.agents.scout import prompts
from app.agents.scout.schemas import RawOpportunity, ScoutCandidate
from app.graph.deps import GraphDeps
from app.providers.llm.base import ChatMessage, LLMRequest, UsageRecord

AGENT = "scout"


def _check_merge_urls(allowed: set[str]) -> Callable[[ScoutCandidate], None]:
    def check(out: ScoutCandidate) -> None:
        bad = sorted({str(s.url) for s in out.signals} - allowed)
        if bad:
            raise ValueError(f"signals cite URLs that no source idea cites: {bad}")

    return check


async def merge_candidate(
    sources: Sequence[RawOpportunity], run_context: str, deps: GraphDeps
) -> tuple[ScoutCandidate, list[UsageRecord]]:
    blocks = "\n\n".join(
        f"<idea_brief>\n"
        f"{neutralise_tags(o.model_dump_json(exclude={'id', 'iteration'}), 'idea_brief')}\n"
        f"</idea_brief>"
        for o in sources
    )
    result = await deps.llm.generate(
        LLMRequest(
            agent=f"{AGENT}.merge",
            model=deps.settings.scout_model,
            system=prompts.MERGE_V1,
            messages=[
                ChatMessage(role="user", content=f"{run_context}\n\nIdeas to merge:\n{blocks}")
            ],
            output_type=ScoutCandidate,
            validator=_check_merge_urls({str(s.url) for o in sources for s in o.signals}),
        )
    )
    return result.output, result.usage
