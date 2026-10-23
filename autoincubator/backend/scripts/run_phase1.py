"""Run the Phase-1 graph from the command line and print the ranked briefs as JSON.

    uv run python scripts/run_phase1.py --seed "independent dental clinics"
    uv run python scripts/run_phase1.py --auto
    uv run python scripts/run_phase1.py --thread-id <id> --resume-select opp-03

Offline: LLM_PROVIDER=fake SEARCH_PROVIDER=mock (the defaults). Needs Postgres (compose up).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.agents.common.brief import ResumePayload
from app.agents.common.schemas import RunInput
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.graph.builder import compile_graph
from app.graph.checkpointer import postgres_checkpointer
from app.graph.state import Phase1State
from app.providers.factory import build_deps


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--seed", help="Mode A: topic, niche, trend or pain point")
    mode.add_argument("--auto", action="store_true", help="Mode B: autonomous signal mining")
    mode.add_argument("--resume-select", metavar="IDEA_ID", help="Resume a paused thread")
    p.add_argument("--thread-id", help="Checkpoint thread id (default: a new uuid)")
    p.add_argument("--region")
    p.add_argument("--business-model", choices=["b2b", "b2c", "any"], default="any")
    p.add_argument("--solo-founder", action="store_true")
    p.add_argument("--exclude", action="append", default=[], metavar="INDUSTRY")
    args = p.parse_args(argv)
    if args.resume_select and not args.thread_id:
        p.error("--resume-select requires --thread-id")
    return args


def _run_input(args: argparse.Namespace) -> RunInput:
    return RunInput.model_validate(
        {
            "mode": "seeded" if args.seed else "autonomous",
            "seed": args.seed,
            "constraints": {
                "region": args.region,
                "business_model": args.business_model,
                "solo_founder": args.solo_founder,
                "excluded_industries": args.exclude,
            },
        }
    )


async def main(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    configure_logging(settings.log_level, stream=sys.stderr)
    thread_id = args.thread_id or str(uuid.uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    deps = build_deps(settings)
    async with postgres_checkpointer(settings) as saver:
        graph = compile_graph(saver)
        if args.resume_select:
            resume = ResumePayload(selected_idea_id=args.resume_select).model_dump()
            await graph.ainvoke(Command(resume=resume), config, context=deps)
        else:
            initial: Phase1State = {"run_id": thread_id, "run_input": _run_input(args)}
            await graph.ainvoke(initial, config, context=deps)
        snapshot = await graph.aget_state(config)

    values = snapshot.values
    usage = values.get("usage", [])
    out: dict[str, Any] = {
        "thread_id": thread_id,
        "status": "interrupted" if snapshot.interrupts else "completed",
        "next": list(snapshot.next),
        "usage": {
            "calls": len(usage),
            "input_tokens": sum(u.input_tokens for u in usage),
            "output_tokens": sum(u.output_tokens for u in usage),
            "cost_usd": round(sum(u.cost_usd for u in usage), 6),
        },
    }
    if snapshot.interrupts:
        out["checkpoint"] = snapshot.interrupts[0].value
    else:
        out["selected_idea_id"] = values.get("selected_idea_id")
        out["phase2"] = values.get("phase2", {})
    return out


if __name__ == "__main__":
    result = asyncio.run(main(parse_args()))
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
