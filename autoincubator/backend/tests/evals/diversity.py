"""Diversity eval: how far apart are the Mode B ideas, within and across runs?

    uv sync --group evals                                  # once: fastembed
    uv run python -m tests.evals.diversity                 # latest collected runs

Embeds title + one-liner + problem of every autonomous brief with a local model (fastembed,
BAAI/bge-small-en-v1.5; downloaded on first use, no API key) and reports cosine distances:
the mean over all pairs, within a run, and across runs, plus near-duplicate pairs across runs
(similarity ≥ 0.9). Higher distance = more varied output. The numbers are only comparable
with the same embedding model.
"""

from __future__ import annotations

import argparse
import itertools
import math
import statistics
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from tests.evals.common import (
    RESULTS,
    CollectedRun,
    append_history,
    git_sha,
    latest_runs_dir,
    load_runs,
    providers,
    stamp,
    write_json,
)

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
NEAR_DUPLICATE = 0.9

Embedder = Callable[[Sequence[str]], list[list[float]]]


def fastembed_embedder(model: str = EMBEDDING_MODEL) -> Embedder:
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise SystemExit("diversity needs the evals group: uv sync --group evals") from exc
    engine = TextEmbedding(model_name=model)

    def embed(texts: Sequence[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in engine.embed(list(texts))]

    return embed


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def ideas(runs: list[CollectedRun]) -> list[tuple[str, str, str]]:
    """(run, title, text) for every brief of every autonomous run."""
    return [
        (
            run.name,
            b.opportunity.title,
            f"{b.opportunity.title}. {b.opportunity.one_liner} {b.opportunity.problem}",
        )
        for run in runs
        if run.mode == "autonomous" and run.checkpoint is not None
        for b in run.checkpoint.briefs
    ]


def spread(items: list[tuple[str, str, str]], vectors: list[list[float]]) -> dict[str, object]:
    within: list[float] = []
    across: list[float] = []
    duplicates: list[dict[str, object]] = []
    for (i, a), (j, b) in itertools.combinations(enumerate(items), 2):
        sim = cosine(vectors[i], vectors[j])
        (within if a[0] == b[0] else across).append(max(0.0, 1 - sim))
        if a[0] != b[0] and sim >= NEAR_DUPLICATE:
            duplicates.append(
                {"a": f"{a[0]}: {a[1]}", "b": f"{b[0]}: {b[1]}", "sim": round(sim, 3)}
            )

    def mean(xs: list[float]) -> float | None:
        return round(statistics.fmean(xs), 3) if xs else None

    return {
        "ideas": len(items),
        "runs": len({run for run, _, _ in items}),
        "mean_distance": mean(within + across),
        "mean_distance_within_run": mean(within),
        "mean_distance_across_runs": mean(across),
        "min_distance_across_runs": round(min(across), 3) if across else None,
        "near_duplicates_across_runs": duplicates,
    }


def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, stream=sys.stderr)
    runs_dir = args.runs or latest_runs_dir()
    runs = load_runs(runs_dir)
    items = ideas(runs)
    if len(items) < 2:
        raise SystemExit(f"need at least two Mode B briefs in {runs_dir}, found {len(items)}")
    vectors = fastembed_embedder()([text for _, _, text in items])
    summary = spread(items, vectors)
    when = stamp()
    out = {
        "eval": "diversity-v1",
        "stamp": when,
        "git_sha": git_sha(),
        "runs_dir": str(runs_dir),
        **providers(runs),
        "embedding_model": EMBEDDING_MODEL,
        **summary,
        "titles": [f"{run}: {title}" for run, title, _ in items],
    }
    path = write_json(RESULTS / f"diversity-{when}.json", out)
    append_history({k: v for k, v in out.items() if k != "titles"})
    for key in ("ideas", "runs", "mean_distance", "mean_distance_within_run",
                "mean_distance_across_runs", "min_distance_across_runs"):  # fmt: skip
        print(f"{key}: {summary[key]}")
    print(f"near duplicates across runs: {summary['near_duplicates_across_runs']}")
    print(f"→ {path}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--runs", type=Path, help="default: the latest collected runs")
    return p.parse_args(argv)


if __name__ == "__main__":
    main(parse_args())
