"""Run Phase 1 for the eval set and save what each run shows at the checkpoint.

    uv run python -m tests.evals.collect                  # 10 seeds + 3 autonomous runs
    uv run python -m tests.evals.collect --only 2 --auto 1 --max-cost 5

Uses LLM_PROVIDER / SEARCH_PROVIDER and the *_MODEL settings from the environment, like the
worker does, but runs the graph in-process on an in-memory checkpointer: no Postgres, no
worker, no daily cap. `--max-cost` is the only spend guard, so keep it. Each run is written to
evals/results/runs/<stamp>/ as soon as it ends; the other evals read that directory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.common.brief import CheckpointPayload
from app.agents.common.schemas import RunInput
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.graph.builder import compile_graph
from app.providers.factory import build_deps
from app.providers.llm.base import UsageRecord
from tests.evals.common import RUNS, CollectedRun, models_of, stamp, summarise_usage, write_json

SEEDS = Path(__file__).with_name("seeds.json")


class SpendLimitError(RuntimeError):
    pass


class Spend:
    """Total LLM spend of this collection, checked before every call."""

    def __init__(self, limit_usd: float):
        self.limit_usd = limit_usd
        self.total_usd = 0.0

    async def before_call(self, agent: str) -> None:
        if self.total_usd >= self.limit_usd:
            raise SpendLimitError(
                f"--max-cost ${self.limit_usd:.2f} reached (${self.total_usd:.2f} spent)"
            )


def run_inputs(seeds_path: Path, only: int | None, autonomous: int) -> list[tuple[str, RunInput]]:
    seeds: list[dict[str, Any]] = json.loads(seeds_path.read_text(encoding="utf-8"))
    out: list[tuple[str, RunInput]] = []
    for i, item in enumerate(seeds[:only] if only is not None else seeds, start=1):
        slug = re.sub(r"[^a-z0-9]+", "-", item["seed"].lower()).strip("-")[:40]
        out.append(
            (
                f"a{i:02d}-{slug}",
                RunInput(mode="seeded", seed=item["seed"], constraints=item.get("constraints", {})),
            )
        )
    out += [(f"b{i:02d}-autonomous", RunInput(mode="autonomous")) for i in range(1, autonomous + 1)]
    return out


async def collect_one(
    name: str, run_input: RunInput, settings: Settings, spend: Spend
) -> CollectedRun:
    usage: list[UsageRecord] = []
    searches = 0

    async def on_usage(record: UsageRecord) -> None:
        usage.append(record)
        spend.total_usd += record.cost_usd

    async def on_search(_query: str) -> None:
        nonlocal searches
        searches += 1

    deps = build_deps(settings, on_usage, before_call=spend.before_call, after_search=on_search)
    config: RunnableConfig = {"configurable": {"thread_id": name}}
    started_at = datetime.now(UTC)
    t0 = time.monotonic()
    checkpoint: CheckpointPayload | None = None
    error: str | None = None
    try:
        result = await compile_graph(InMemorySaver()).ainvoke(
            {"run_id": name, "run_input": run_input}, config, context=deps
        )
        interrupts = result.get("__interrupt__") or []
        if interrupts:
            checkpoint = CheckpointPayload.model_validate(interrupts[0].value)
        else:
            error = "the run ended without reaching the checkpoint"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return CollectedRun(
        name=name,
        mode=run_input.mode,
        seed=run_input.seed,
        constraints=run_input.constraints.model_dump(),
        started_at=started_at,
        duration_s=round(time.monotonic() - t0, 1),
        llm_provider=settings.llm_provider,
        search_provider=settings.search_provider,
        models=models_of(settings),
        usage=summarise_usage(usage),
        searches=searches,
        checkpoint=checkpoint,
        error=error,
    )


def describe(run: CollectedRun) -> str:
    if run.checkpoint is None:
        outcome = f"ERROR {run.error}"
    else:
        outcome = f"{len(run.checkpoint.briefs)} briefs"
        if run.checkpoint.shortfall:
            outcome += " (shortfall)"
    return (
        f"{run.name:<50} {outcome:<24} ${run.cost_usd:>7.3f}  "
        f"{run.searches:>3} searches  {run.duration_s:>6.1f}s"
    )


async def main(args: argparse.Namespace) -> Path:
    settings = get_settings()
    configure_logging(settings.log_level, stream=sys.stderr)
    if not args.allow_offline and (
        settings.llm_provider == "fake" or settings.search_provider == "mock"
    ):
        raise SystemExit(
            "evals need LLM_PROVIDER=anthropic and a real SEARCH_PROVIDER "
            "(pass --allow-offline for a smoke test with the fakes)"
        )
    out_dir = args.out or RUNS / stamp()
    spend = Spend(args.max_cost)
    for name, run_input in run_inputs(args.seeds, args.only, args.auto):
        run = await collect_one(name, run_input, settings, spend)
        write_json(out_dir / f"{name}.json", run.model_dump(mode="json"))
        print(describe(run), flush=True)
        if run.error and "SpendLimitError" in run.error:
            break
    print(f"\ntotal ${spend.total_usd:.3f} → {out_dir}")
    return out_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--seeds", type=Path, default=SEEDS)
    p.add_argument("--only", type=int, help="use the first N seeds only")
    p.add_argument("--auto", type=int, default=3, help="number of Mode B runs (default 3)")
    p.add_argument("--max-cost", type=float, default=30.0, help="USD, whole collection")
    p.add_argument("--out", type=Path, help="default: evals/results/runs/<stamp>")
    p.add_argument("--allow-offline", action="store_true")
    return p.parse_args(argv)


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
