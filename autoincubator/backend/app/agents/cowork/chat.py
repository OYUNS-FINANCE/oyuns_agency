"""One co-working turn: the founder's message → the agent's reply and an optional patch.

Not a graph node: co-working runs outside the paused graph (ADR 0006).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.agents.common.untrusted import neutralise_tags
from app.agents.cowork import prompts
from app.agents.cowork.schemas import CoworkInput, CoworkOutput
from app.agents.cowork.stream import ReplyStreamReader
from app.core.config import Settings
from app.providers.llm.base import ChatMessage, LLMProvider, LLMRequest, UsageRecord
from app.services.brief_patch import EditableBrief, PatchOperation, apply_patch

TextHook = Callable[[str], Awaitable[None]]
ResetHook = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class CoworkTurn:
    output: CoworkOutput
    patch: list[PatchOperation]
    usage: list[UsageRecord]


def model_for(agent: str, settings: Settings) -> str:
    return {
        "scout": settings.scout_model,
        "analyst": settings.analyst_model,
        "skeptic": settings.skeptic_model,
    }[agent]


def render_turn(inp: CoworkInput) -> str:
    """The whole conversation as one user message: past turns of every agent on this idea,
    so a persona knows what the others already said."""
    names = {"scout": "Trend Scout", "analyst": "Market Analyst", "skeptic": "Devil's Advocate"}
    transcript = "\n\n".join(
        f"{'Founder' if line.role == 'user' else names[line.agent]}: {line.content}"
        for line in inp.history
    )
    brief = neutralise_tags(inp.brief_json, prompts.BRIEF_TAG)
    return (
        f"{inp.run_context}\n\n"
        f"Idea brief, version {inp.version}:\n{prompts.BRIEF_OPEN}\n{brief}\n"
        f"{prompts.BRIEF_CLOSE}\n\n"
        f"Conversation so far:\n{transcript or '(none)'}\n\n"
        f"Founder (to the {names[inp.agent]}): {inp.message}"
    )


def _check_patch(current: EditableBrief) -> Callable[[CoworkOutput], None]:
    def check(out: CoworkOutput) -> None:
        if out.edits:
            apply_patch(current, out.patch())  # PatchError is a ValueError → retry

    return check


async def cowork_reply(
    inp: CoworkInput,
    current: EditableBrief,
    llm: LLMProvider,
    settings: Settings,
    *,
    on_text: TextHook,
    on_reset: ResetHook,
) -> CoworkTurn:
    """Streams the reply text through `on_text`. A validation retry calls `on_reset` first:
    the client discards the text it showed and the new attempt streams from the start."""
    reader = ReplyStreamReader()
    current_attempt = 1

    async def on_delta(chunk: str, attempt: int) -> None:
        nonlocal reader, current_attempt
        if attempt != current_attempt:
            current_attempt = attempt
            reader = ReplyStreamReader()
            await on_reset()
        if text := reader.feed(chunk):
            await on_text(text)

    result = await llm.generate(
        LLMRequest(
            agent=f"cowork.{inp.agent}",
            model=model_for(inp.agent, settings),
            system=prompts.system_prompt(inp.agent),
            messages=[ChatMessage(role="user", content=render_turn(inp))],
            output_type=CoworkOutput,
            max_tokens=8_000,
            validator=_check_patch(current),
            on_delta=on_delta,
        )
    )
    return CoworkTurn(output=result.output, patch=result.output.patch(), usage=result.usage)
