"""Grounding eval: do the cited pages support the sourced figures?

    uv run python -m tests.evals.grounding                       # latest collected runs
    uv run python -m tests.evals.grounding --runs DIR --sample 40

Samples figures that carry a `source_url` from the briefs in the collected runs, fetches each
page, and asks a judge model whether the page supports the figure (prompts.GROUNDING_SYSTEM).
Pages that cannot be read are failures with their cause, never skipped: the headline number is
supported / sampled. The share among readable pages is reported next to it.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import re
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

import httpx
from pydantic import BaseModel, Field, model_validator

from app.agents.analyst.schemas import MarketAnalysis, SourcedFigure
from app.agents.common.untrusted import neutralise_tags
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.providers.factory import build_llm
from app.providers.llm.base import ChatMessage, LLMOutputError, LLMProvider, LLMRequest, UsageRecord
from app.providers.search.sanitize import strip_invisible, strip_markup, tidy
from tests.evals import prompts
from tests.evals.common import (
    RESULTS,
    CollectedRun,
    append_history,
    git_sha,
    judge_cost,
    latest_runs_dir,
    load_runs,
    pct,
    providers,
    stamp,
    write_json,
)

USER_AGENT = "Mozilla/5.0 (compatible; AutoIncubator-eval/1.0; grounding check)"
PAGE_TAG = "source_page"
MAX_PAGE_CHARS = 20_000
HEAD_CHARS = 4_000
WINDOW_CHARS = 700
_PAYWALL = re.compile(
    r"subscribe to (continue|read)|create a free account to|sign in to (continue|read)"
    r"|enable javascript|verify you are (a )?human|access denied",
    re.I,
)
_WS = re.compile(r"\s+")

FetchStatus = Literal["ok", "dead_link", "blocked", "timeout", "http_error", "unreadable"]
Verdict = Literal["supported", "partial", "unsupported"]
Cause = Literal["none", "wrong_number", "different_metric", "derived", "not_on_page"]


@dataclass(frozen=True)
class Claim:
    run: str
    idea_id: str
    idea_title: str
    label: str
    value: float
    unit: str
    url: str

    def describe(self) -> str:
        return f"{self.label}: {self.value:,.6g} {self.unit}"


def claims_of(analysis: MarketAnalysis, run: str, idea_id: str, title: str) -> list[Claim]:
    labelled: list[tuple[str, SourcedFigure]] = [
        (f"TAM ({analysis.sizing.method})", analysis.sizing.tam),
        (f"SAM ({analysis.sizing.method})", analysis.sizing.sam),
        (f"SOM ({analysis.sizing.method})", analysis.sizing.som),
    ]
    labelled += [(f"price of {c.name}", c.price) for c in analysis.competitors if c.price]
    labelled += [
        (f"{p.billing} price of {p.product}", p.price) for p in analysis.pricing_benchmarks
    ]
    labelled += [
        (f"size of segment '{s.name}' ({s.description})", s.size)
        for s in analysis.segments
        if s.size
    ]
    return [
        Claim(run, idea_id, title, label, fig.value, fig.unit, str(fig.source_url))
        for label, fig in labelled
        if fig.source_url is not None
    ]


def population(runs: list[CollectedRun]) -> list[Claim]:
    """Every sourced figure in every brief, one per (url, value, unit)."""
    seen: set[tuple[str, float, str]] = set()
    out: list[Claim] = []
    for run in runs:
        if run.checkpoint is None:
            continue
        for brief in run.checkpoint.briefs:
            for claim in claims_of(
                brief.analysis, run.name, brief.idea_id, brief.opportunity.title
            ):
                key = (claim.url, claim.value, claim.unit)
                if key not in seen:
                    seen.add(key)
                    out.append(claim)
    return out


def sample(claims: list[Claim], n: int, seed: int) -> list[Claim]:
    return claims if len(claims) <= n else random.Random(seed).sample(claims, n)


@dataclass(frozen=True)
class Page:
    status: FetchStatus
    detail: str
    text: str = ""


async def fetch(client: httpx.AsyncClient, url: str, max_bytes: int) -> Page:
    try:
        async with client.stream("GET", url) as resp:
            if resp.status_code in (404, 410):
                return Page("dead_link", f"HTTP {resp.status_code}")
            if resp.status_code in (401, 402, 403, 429, 451):
                return Page("blocked", f"HTTP {resp.status_code}")
            if resp.status_code >= 400:
                return Page("http_error", f"HTTP {resp.status_code}")
            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype and not (ctype.startswith("text/") or ctype.endswith(("+xml", "/json"))):
                return Page("unreadable", ctype)
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) >= max_bytes:
                    break
            raw = bytes(body).decode(resp.encoding or "utf-8", errors="replace")
    except httpx.TimeoutException:
        return Page("timeout", "timed out")
    except httpx.HTTPError as exc:
        return Page("dead_link", f"{type(exc).__name__}: {exc}"[:200])
    text = tidy(strip_invisible(strip_markup(raw)))
    if len(text) < 400 and _PAYWALL.search(text):
        return Page("blocked", "paywall or bot check")
    if len(text) < 200:
        return Page("blocked" if _PAYWALL.search(text) else "unreadable", "almost no text")
    return Page("ok", f"{len(text)} chars", text)


def number_tokens(value: float) -> set[str]:
    """How `value` may be written on a page: 4200000000 → 4,200,000,000 / 4200000000 / 4.2."""
    tokens = {f"{value:,.0f}", f"{value:.0f}", f"{value:g}"}
    for scale in (1e12, 1e9, 1e6, 1e3):
        if value >= scale:
            mantissa = value / scale
            tokens |= {f"{mantissa:.1f}", f"{mantissa:.2f}", f"{mantissa:.0f}"}
            break
    if value < 1:
        tokens.add(f"{value * 100:g}")  # a share written as a percentage
    return {t.rstrip("0").rstrip(".") if "." in t else t for t in tokens if t not in ("0", "")}


def excerpt(text: str, value: float) -> str:
    """The page as the judge sees it: all of a short page; the head plus windows around
    matches of the number for a long one."""
    if len(text) <= MAX_PAGE_CHARS:
        return text
    spans: list[tuple[int, int]] = []
    for token in number_tokens(value):
        for m in re.finditer(rf"(?<![\d.]){re.escape(token)}(?![\d])", text):
            spans.append((max(0, m.start() - WINDOW_CHARS), m.end() + WINDOW_CHARS))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    parts = [text[:HEAD_CHARS]]
    budget = MAX_PAGE_CHARS - HEAD_CHARS
    for start, end in merged:
        start = max(start, HEAD_CHARS)
        if end <= start:
            continue
        chunk = text[start:end]
        if len(chunk) > budget:
            break
        parts.append(chunk)
        budget -= len(chunk)
    return "\n[…]\n".join(parts)


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


class GroundingJudgement(BaseModel):
    verdict: Verdict
    cause: Cause
    quote: str = Field(max_length=400)
    reasoning: str = Field(max_length=800)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.verdict == "supported") != (self.cause == "none"):
            raise ValueError('cause must be "none" exactly when the verdict is "supported"')
        if self.verdict != "unsupported" and not self.quote.strip():
            raise ValueError("a supported or partial verdict needs the quote it relies on")
        return self


def quote_validator(page: str) -> Callable[[GroundingJudgement], None]:
    page_norm = _norm(page)

    def check(j: GroundingJudgement) -> None:
        quote = _norm(j.quote.strip("\"'…. "))
        if quote and quote not in page_norm:
            raise ValueError("`quote` must be copied verbatim from the page text")

    return check


async def judge(
    llm: LLMProvider, model: str, claim: Claim, page: str
) -> tuple[GroundingJudgement, list[UsageRecord]]:
    content = (
        f"Claim (from a brief about “{claim.idea_title}”):\n{claim.describe()}\n"
        f"Cited URL: {claim.url}\n\n"
        f"<{PAGE_TAG}>\n{neutralise_tags(page, PAGE_TAG)}\n</{PAGE_TAG}>"
    )
    result = await llm.generate(
        LLMRequest(
            agent="eval.grounding",
            model=model,
            system=prompts.GROUNDING_SYSTEM,
            messages=[ChatMessage(role="user", content=content)],
            output_type=GroundingJudgement,
            max_tokens=1_500,
            validator=quote_validator(page),
        )
    )
    return result.output, result.usage


class ItemResult(BaseModel):
    run: str
    idea_id: str
    idea_title: str
    claim: str
    url: str
    fetch: FetchStatus
    fetch_detail: str
    verdict: Verdict | None = None
    cause: str
    quote: str = ""
    reasoning: str = ""

    @property
    def supported(self) -> bool:
        return self.verdict == "supported"


async def evaluate(
    claims: list[Claim],
    llm: LLMProvider,
    model: str,
    settings: Settings,
    client: httpx.AsyncClient,
    concurrency: int = 4,
) -> tuple[list[ItemResult], list[UsageRecord]]:
    gate = asyncio.Semaphore(concurrency)
    usage: list[UsageRecord] = []

    async def one(claim: Claim) -> ItemResult:
        async with gate:
            page = await fetch(client, claim.url, settings.page_fetch_max_bytes)
            base = {
                "run": claim.run,
                "idea_id": claim.idea_id,
                "idea_title": claim.idea_title,
                "claim": claim.describe(),
                "url": claim.url,
                "fetch": page.status,
                "fetch_detail": page.detail,
            }
            if page.status != "ok":
                return ItemResult(**base, cause=page.status)
            try:
                j, u = await judge(llm, model, claim, excerpt(page.text, claim.value))
            except LLMOutputError as exc:
                usage.extend(exc.usage)
                return ItemResult(**base, cause="judge_error", reasoning=str(exc)[:500])
            usage.extend(u)
            return ItemResult(
                **base, verdict=j.verdict, cause=j.cause, quote=j.quote, reasoning=j.reasoning
            )

    return list(await asyncio.gather(*(one(c) for c in claims))), usage


def summarise(items: list[ItemResult]) -> dict[str, object]:
    readable = [i for i in items if i.fetch == "ok"]
    supported = sum(i.supported for i in items)
    return {
        "sampled": len(items),
        "readable": len(readable),
        "supported": supported,
        "partial": sum(i.verdict == "partial" for i in items),
        "supported_pct": pct(supported, len(items)),
        "supported_pct_of_readable": pct(supported, len(readable)),
        "supported_or_partial_pct": pct(
            sum(i.verdict in ("supported", "partial") for i in items), len(items)
        ),
        "failure_causes": dict(Counter(i.cause for i in items if not i.supported).most_common()),
    }


def report(summary: dict[str, object], items: list[ItemResult]) -> str:
    lines = [
        f"Grounding: {summary['supported']}/{summary['sampled']} supported "
        f"({summary['supported_pct']}%), {summary['supported_pct_of_readable']}% of the "
        f"{summary['readable']} readable pages; supported or partial "
        f"{summary['supported_or_partial_pct']}%.",
        f"Failure causes: {summary['failure_causes']}",
        "",
        "| verdict | cause | claim | url |",
        "|---|---|---|---|",
    ]
    for i in sorted(items, key=lambda i: (i.supported, i.cause)):
        if not i.supported:
            lines.append(f"| {i.verdict or '—'} | {i.cause} | {i.claim[:90]} | {i.url} |")
    return "\n".join(lines)


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, stream=sys.stderr)
    runs_dir = args.runs or latest_runs_dir()
    runs = load_runs(runs_dir)
    claims = population(runs)
    chosen = sample(claims, args.sample, args.seed)
    llm = build_llm(settings)
    async with httpx.AsyncClient(
        timeout=settings.page_fetch_timeout_s,
        follow_redirects=True,
        headers={"user-agent": USER_AGENT},
    ) as client:
        items, usage = await evaluate(chosen, llm, args.judge_model, settings, client)
    summary = summarise(items)
    when = stamp()
    out = {
        "eval": prompts.GROUNDING_VERSION,
        "stamp": when,
        "git_sha": git_sha(),
        "runs_dir": str(runs_dir),
        **providers(runs),
        "judge_model": args.judge_model,
        "population": len(claims),
        "judge_cost_usd": judge_cost(usage),
        **summary,
        "items": [i.model_dump() for i in items],
    }
    path = write_json(RESULTS / f"grounding-{when}.json", out)
    append_history({k: v for k, v in out.items() if k != "items"})
    print(report(summary, items))
    print(f"\njudge cost ${out['judge_cost_usd']:.3f} → {path}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--runs", type=Path, help="default: the latest collected runs")
    p.add_argument("--sample", type=int, default=40)
    p.add_argument("--seed", type=int, default=7, help="sampling seed")
    p.add_argument("--judge-model", default="claude-sonnet-5-5")
    return p.parse_args(argv)


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
