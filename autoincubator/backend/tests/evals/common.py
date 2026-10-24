"""Shared plumbing for the manual evals: paths, collected-run files, judge usage, output."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from app.agents.common.brief import CheckpointPayload
from app.core.config import Settings
from app.providers.llm.base import UsageRecord

BACKEND = Path(__file__).resolve().parents[2]
RESULTS = BACKEND / "evals" / "results"
RUNS = RESULTS / "runs"
HISTORY = RESULTS / "history.jsonl"


class AgentUsage(BaseModel):
    agent: str
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float = 0.0


class CollectedRun(BaseModel):
    """One Phase-1 run as `collect` saved it: what the founder would see at the checkpoint."""

    name: str
    mode: Literal["seeded", "autonomous"]
    seed: str | None
    constraints: dict[str, Any]
    started_at: datetime
    duration_s: float
    llm_provider: str
    search_provider: str
    models: dict[str, str]
    usage: list[AgentUsage]
    searches: int
    checkpoint: CheckpointPayload | None
    error: str | None = None

    @property
    def cost_usd(self) -> float:
        return sum(u.cost_usd for u in self.usage)


def summarise_usage(records: list[UsageRecord]) -> list[AgentUsage]:
    by: dict[tuple[str, str], AgentUsage] = {}
    for r in records:
        row = by.setdefault((r.agent, r.model), AgentUsage(agent=r.agent, model=r.model))
        row.calls += 1
        row.input_tokens += r.input_tokens
        row.output_tokens += r.output_tokens
        row.cache_read_input_tokens += r.cache_read_input_tokens
        row.cost_usd += r.cost_usd
    return sorted(by.values(), key=lambda u: -u.cost_usd)


def judge_cost(records: list[UsageRecord]) -> float:
    return round(sum(r.cost_usd for r in records), 6)


def models_of(settings: Settings) -> dict[str, str]:
    return {
        "scout": settings.scout_model,
        "analyst": settings.analyst_model,
        "skeptic": settings.skeptic_model,
    }


def stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BACKEND,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip()


def latest_runs_dir() -> Path:
    dirs = sorted(p for p in RUNS.glob("*") if p.is_dir())
    if not dirs:
        raise SystemExit(f"no collected runs under {RUNS}; run `python -m tests.evals.collect`")
    return dirs[-1]


def load_runs(directory: Path) -> list[CollectedRun]:
    return [
        CollectedRun.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.json"))
    ]


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def append_history(entry: dict[str, Any]) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")


def providers(runs: list[CollectedRun]) -> dict[str, object]:
    """Which providers produced the runs; `offline` marks a smoke test on the fakes."""
    llm = sorted({r.llm_provider for r in runs})
    search = sorted({r.search_provider for r in runs})
    return {
        "llm_provider": llm,
        "search_provider": search,
        "pipeline_models": runs[0].models if runs else {},
        "offline": "fake" in llm or "mock" in search,
    }


def pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0
