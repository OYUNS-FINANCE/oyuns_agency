"""Idea-quality eval: a strong model grades the top briefs of every collected run.

    uv run python -m tests.evals.quality                          # latest collected runs
    uv run python -m tests.evals.quality --runs DIR --top 3

Rubric and anchors: prompts.QUALITY_SYSTEM (1-5 on five dimensions). Writes
evals/results/quality-<stamp>.json and appends the means to evals/results/history.jsonl, so
scores can be compared over time (only within the same prompt version and judge model).
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.common.brief import IdeaBrief
from app.agents.common.untrusted import neutralise_tags
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.providers.factory import build_llm
from app.providers.llm.base import ChatMessage, LLMProvider, LLMRequest, UsageRecord
from tests.evals import prompts
from tests.evals.common import (
    RESULTS,
    CollectedRun,
    append_history,
    git_sha,
    judge_cost,
    latest_runs_dir,
    load_runs,
    providers,
    stamp,
    write_json,
)

DIMENSIONS = ("specificity", "evidence", "solo_founder_fit", "differentiation", "risk_honesty")
BRIEF_TAG = "idea_brief"


class Grade(BaseModel):
    score: int = Field(ge=1, le=5)
    justification: str = Field(min_length=5, max_length=400)


class QualityJudgement(BaseModel):
    specificity: Grade
    evidence: Grade
    solo_founder_fit: Grade
    differentiation: Grade
    risk_honesty: Grade
    worth_a_week: bool
    verdict: str = Field(min_length=5, max_length=600)

    def scores(self) -> dict[str, int]:
        return {d: getattr(self, d).score for d in DIMENSIONS}

    @property
    def mean(self) -> float:
        return statistics.fmean(self.scores().values())


def brief_text(run: CollectedRun, brief: IdeaBrief) -> str:
    """The brief as the founder sees it, minus ids and bookkeeping."""
    body = brief.model_dump_json(
        indent=1,
        exclude={
            "opportunity": {"id", "iteration"},
            "analysis": {"opportunity_id"},
            "critique": {"opportunity_id"},
        },
    )
    context = f"Run mode: {run.mode}" + (f"; seed: {run.seed}" if run.seed else "")
    context += f"; constraints: {run.constraints}"
    return f"{context}\n\n<{BRIEF_TAG}>\n{neutralise_tags(body, BRIEF_TAG)}\n</{BRIEF_TAG}>"


async def grade(
    llm: LLMProvider, model: str, run: CollectedRun, brief: IdeaBrief
) -> tuple[QualityJudgement, list[UsageRecord]]:
    result = await llm.generate(
        LLMRequest(
            agent="eval.quality",
            model=model,
            system=prompts.QUALITY_SYSTEM,
            messages=[ChatMessage(role="user", content=brief_text(run, brief))],
            output_type=QualityJudgement,
            max_tokens=2_000,
        )
    )
    return result.output, result.usage


class BriefGrade(BaseModel):
    run: str
    mode: Literal["seeded", "autonomous"]
    rank: int
    title: str
    composite_score: float
    judgement: QualityJudgement


async def evaluate(
    runs: list[CollectedRun], llm: LLMProvider, model: str, top: int, concurrency: int = 4
) -> tuple[list[BriefGrade], list[UsageRecord]]:
    gate = asyncio.Semaphore(concurrency)
    usage: list[UsageRecord] = []

    async def one(run: CollectedRun, brief: IdeaBrief) -> BriefGrade:
        async with gate:
            judgement, u = await grade(llm, model, run, brief)
        usage.extend(u)
        return BriefGrade(
            run=run.name,
            mode=run.mode,
            rank=brief.rank,
            title=brief.opportunity.title,
            composite_score=brief.composite_score,
            judgement=judgement,
        )

    jobs = [
        one(run, brief)
        for run in runs
        if run.checkpoint is not None
        for brief in run.checkpoint.briefs[:top]
    ]
    return list(await asyncio.gather(*jobs)), usage


def summarise(grades: list[BriefGrade], runs: list[CollectedRun]) -> dict[str, object]:
    def means(rows: list[BriefGrade]) -> dict[str, float]:
        if not rows:
            return {}
        out = {
            d: round(statistics.fmean(r.judgement.scores()[d] for r in rows), 2) for d in DIMENSIONS
        }
        out["overall"] = round(statistics.fmean(r.judgement.mean for r in rows), 2)
        out["worth_a_week_pct"] = round(
            100 * sum(r.judgement.worth_a_week for r in rows) / len(rows), 1
        )
        return out

    composite = [r.composite_score for r in grades]
    judged = [r.judgement.mean for r in grades]
    correlation = (
        round(statistics.correlation(composite, judged), 2)
        if len(grades) >= 3 and len(set(composite)) > 1 and len(set(judged)) > 1
        else None
    )
    return {
        "briefs": len(grades),
        "runs_without_briefs": [
            r.name for r in runs if not r.checkpoint or not r.checkpoint.briefs
        ],
        "means": means(grades),
        "means_seeded": means([g for g in grades if g.mode == "seeded"]),
        "means_autonomous": means([g for g in grades if g.mode == "autonomous"]),
        "pipeline_vs_judge_correlation": correlation,
    }


def report(summary: dict[str, object], grades: list[BriefGrade]) -> str:
    lines = [
        f"Quality over {summary['briefs']} briefs: {summary['means']}",
        f"Seeded: {summary['means_seeded']}",
        f"Autonomous: {summary['means_autonomous']}",
        f"Pipeline composite vs judge mean (Pearson): {summary['pipeline_vs_judge_correlation']}",
        "",
        "| run | # | idea | " + " | ".join(DIMENSIONS) + " | week? |",
        "|---|---|---|" + "---|" * len(DIMENSIONS) + "---|",
    ]
    for g in grades:
        s = g.judgement.scores()
        lines.append(
            f"| {g.run} | {g.rank} | {g.title[:50]} | "
            + " | ".join(str(s[d]) for d in DIMENSIONS)
            + f" | {'yes' if g.judgement.worth_a_week else 'no'} |"
        )
    return "\n".join(lines)


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, stream=sys.stderr)
    runs_dir = args.runs or latest_runs_dir()
    runs = load_runs(runs_dir)
    grades, usage = await evaluate(runs, build_llm(settings), args.judge_model, args.top)
    summary = summarise(grades, runs)
    when = stamp()
    out = {
        "eval": prompts.QUALITY_VERSION,
        "stamp": when,
        "git_sha": git_sha(),
        "runs_dir": str(runs_dir),
        **providers(runs),
        "judge_model": args.judge_model,
        "judge_cost_usd": judge_cost(usage),
        **summary,
        "grades": [g.model_dump() for g in grades],
    }
    path = write_json(RESULTS / f"quality-{when}.json", out)
    append_history({k: v for k, v in out.items() if k != "grades"})
    print(report(summary, grades))
    print(f"\njudge cost ${out['judge_cost_usd']:.3f} → {path}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--runs", type=Path, help="default: the latest collected runs")
    p.add_argument("--top", type=int, default=3, help="briefs per run (default 3)")
    p.add_argument("--judge-model", default="claude-opus-5-5")
    return p.parse_args(argv)


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
