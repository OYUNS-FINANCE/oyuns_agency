"""FakeLLM: scripted responses for tests, plus a deterministic offline responder for the CLI."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.providers.llm.base import (
    BeforeCallHook,
    ChatMessage,
    DeltaHook,
    LLMRequest,
    RawCompletion,
    StructuredLLMProvider,
    UsageHook,
    UsageRecord,
)

Scripted = BaseModel | Mapping[str, Any] | str
"""A model instance, a dict (dumped to JSON, may be invalid on purpose) or raw text."""
Responder = Callable[[LLMRequest[BaseModel], Sequence[ChatMessage]], Scripted]


@dataclass(frozen=True)
class FakeCall:
    agent: str
    model: str
    system: str
    messages: tuple[ChatMessage, ...]
    attempt: int


def _to_text(item: Scripted) -> str:
    if isinstance(item, BaseModel):
        return item.model_dump_json()
    if isinstance(item, str):
        return item
    return json.dumps(item, default=str)


class FakeLLM(StructuredLLMProvider):
    """Pops scripted responses per agent name, in order; falls back to `responder`.

    Runs the same validate-and-retry loop as the real provider, so an invalid scripted
    response followed by a valid one exercises the retry path.
    """

    def __init__(
        self,
        script: Mapping[str, Sequence[Scripted]] | None = None,
        *,
        responder: Responder | None = None,
        max_validation_retries: int = 2,
        usage_hook: UsageHook | None = None,
        before_call: BeforeCallHook | None = None,
        latency_s: float = 0.0,
    ):
        super().__init__(
            max_validation_retries=max_validation_retries,
            usage_hook=usage_hook,
            before_call=before_call,
        )
        self.latency_s = latency_s
        self._queues: dict[str, deque[Scripted]] = defaultdict(deque)
        for agent, items in (script or {}).items():
            self._queues[agent].extend(items)
        self.responder = responder
        self.calls: list[FakeCall] = []

    def remaining(self, agent: str) -> int:
        return len(self._queues[agent])

    async def _complete(
        self, request: LLMRequest[BaseModel], messages: Sequence[ChatMessage], attempt: int
    ) -> RawCompletion:
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        self.calls.append(
            FakeCall(request.agent, request.model, request.system, tuple(messages), attempt)
        )
        queue = self._queues[request.agent]
        if queue:
            item = queue.popleft()
        elif self.responder is not None:
            item = self.responder(request, messages)
        else:
            raise LookupError(f"FakeLLM has no scripted response left for agent {request.agent!r}")
        text = _to_text(item)
        if request.on_delta is not None:
            await _stream(text, request.on_delta, attempt)
        prompt_chars = len(request.system) + sum(len(m.content) for m in messages)
        usage = UsageRecord(
            agent=request.agent,
            model=f"fake:{request.model}",
            input_tokens=prompt_chars // 4,
            output_tokens=len(text) // 4,
            cost_usd=0.0,
            attempt=attempt,
        )
        return RawCompletion(text=text, usage=usage)


STREAM_CHUNK_CHARS = 24
STREAM_CHUNK_DELAY_S = 0.01


async def _stream(text: str, on_delta: DeltaHook, attempt: int) -> None:
    """Delivers scripted text in small chunks, like a real token stream."""
    for i in range(0, len(text), STREAM_CHUNK_CHARS):
        await on_delta(text[i : i + STREAM_CHUNK_CHARS], attempt)
        await asyncio.sleep(STREAM_CHUNK_DELAY_S)


# --- Offline responder -------------------------------------------------------------------

_RESULT = re.compile(r"\[(\d+)\] title: (.*)\nurl: (\S+)\nsnippet: (.*)")
_INJECTION = re.compile(r"ignore (all )?previous instructions|admin mode", re.IGNORECASE)
_CATEGORIES = (
    "rising_search",
    "funding_round",
    "new_regulation",
    "complaint_thread",
    "manual_work_job_posting",
    "marketplace_gap",
)
_AUTO_INDUSTRIES = (
    "healthcare",
    "home services",
    "real estate",
    "education",
    "fashion",
    "finance",
)
_DIMENSIONS = (
    "cac_risk",
    "channel_dependency",
    "churn_risk",
    "defensibility",
    "regulatory_risk",
    "time_to_first_revenue",
    "solo_founder_feasibility",
)


def _h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def _user_text(messages: Sequence[ChatMessage]) -> str:
    return messages[0].content if messages else ""


def _results(text: str) -> list[tuple[str, str, str]]:
    return [
        (title.strip(), url, snippet.strip())
        for _, title, url, snippet in _RESULT.findall(text)
        if not _INJECTION.search(f"{title} {snippet}")
    ]


def _plan(text: str) -> dict[str, Any]:
    seed = re.search(r"Seed: (.*)", text)
    queries = []
    if seed:
        topic = seed.group(1).strip()
        for cat in _CATEGORIES:
            queries.append(
                {
                    "category": cat,
                    "industry": topic[:60],
                    "query": f"{topic[:150]} {cat.replace('_', ' ')}",
                }
            )
    else:
        for i, cat in enumerate(_CATEGORIES):
            for j in range(2):
                industry = _AUTO_INDUSTRIES[(i + 2 * j) % len(_AUTO_INDUSTRIES)]
                queries.append(
                    {
                        "category": cat,
                        "industry": industry,
                        "query": f"{industry} {cat.replace('_', ' ')}",
                    }
                )
    return {"queries": queries}


def _extract(text: str, target: int) -> dict[str, Any]:
    candidates = []
    for title, url, snippet in _results(text)[:target]:
        h = _h(url)
        candidates.append(
            {
                "title": f"Tooling for: {title[:90]}",
                "one_liner": f"A focused product addressing the problem reported in: {title[:200]}",
                "problem": snippet[:780] or title,
                "target_customer": "Small operators affected by the reported problem",
                "industry": title.split()[0].lower(),
                "business_model": "b2b" if h % 3 else "b2c",
                "signals": [
                    {
                        "category": _CATEGORIES[h % len(_CATEGORIES)],
                        "url": url,
                        "evidence": snippet[:390] or title,
                    }
                ],
                "novelty_score": 4 + h % 6,
                "signal_strength": 5 + h % 5,
                "is_generic": False,
            }
        )
    return {"candidates": candidates}


def _figure(value: float, unit: str, url: str | None, note: str) -> dict[str, Any]:
    if url:
        return {"value": value, "unit": unit, "source_url": url, "assumption": None}
    return {"value": value, "unit": unit, "source_url": None, "assumption": note}


def _analysis(text: str) -> dict[str, Any]:
    urls = [u for _, u, _ in _results(text)]
    key = text  # the whole prompt: deterministic and distinct per opportunity
    tam = 1_000_000_000 + _h(key, "tam") % 4_000_000_000
    sam = tam // 10
    som = sam // 50
    first = urls[0] if urls else None
    second = urls[1] if len(urls) > 1 else None
    return {
        "sizing": {
            "method": "top_down",
            "method_explanation": (
                "Top-down: sector spend from the cited report, narrowed by segment share."
            ),
            "tam": _figure(tam, "USD/year", first, "Offline estimate: no source available."),
            "sam": _figure(
                sam, "USD/year", None, "Assumed 10% of TAM is reachable small operators."
            ),
            "som": _figure(som, "USD/year", None, "Assumed 2% of SAM captured within three years."),
        },
        "competitors": [
            {
                "name": "Incumbent suite",
                "url": second,
                "positioning": "Broad tool aimed at larger customers.",
                "price": _figure(
                    49 + _h(key, "p") % 80,
                    "USD/month",
                    second,
                    "Typical SaaS seat price (assumed).",
                ),
            }
        ],
        "pricing_benchmarks": [
            {
                "product": "Comparable point solution",
                "price": _figure(
                    29 + _h(key, "b") % 50,
                    "USD/month",
                    None,
                    "Assumed from typical SMB SaaS tiers.",
                ),
                "billing": "monthly",
            }
        ],
        "segments": [
            {
                "name": "Independent operators",
                "description": "Owner-run businesses with under 20 staff.",
                "size": None,
            }
        ],
        "summary": "Offline analysis generated deterministically from mock search results.",
    }


def _critique(text: str) -> dict[str, Any]:
    key = text  # the whole prompt: deterministic and distinct per opportunity
    base = 3 + _h(key, "base") % 7  # per-idea level, so composites spread across 2-10
    scores = [
        {
            "dimension": d,
            "score": min(10, max(1, base + _h(key, d) % 3 - 1)),
            "justification": f"Deterministic offline score for {d.replace('_', ' ')}.",
        }
        for d in _DIMENSIONS
    ]
    return {
        "scores": scores,
        "most_likely_failure_cause": (
            "Customers keep their current manual process because switching feels risky."
        ),
        "attack_summary": (
            "Offline critique generated deterministically; scores vary by opportunity id."
        ),
    }


_BRIEF = re.compile(r"<idea_brief>\n(.*?)\n</idea_brief>", re.DOTALL)
_FOUNDER = re.compile(r"Founder \(to the [^)]*\): (.*)\Z", re.DOTALL)


def _briefs(text: str) -> list[dict[str, Any]]:
    return [json.loads(b) for b in _BRIEF.findall(text)]


def _cowork(agent: str, text: str) -> dict[str, Any]:
    """A short reply and, unless the founder says "no change", one edit to the one-liner
    that folds the founder's message in. Deterministic, so UI tests can rely on it."""
    founder = _FOUNDER.search(text)
    message = founder.group(1).strip() if founder else ""
    (brief,) = _briefs(text) or [{}]
    title = str(brief.get("opportunity", {}).get("title", "this idea"))
    reply = (
        f"Offline {agent} reply about {title!r}. You said: {message[:200]}. "
        "Here is a sharper one-liner that reflects it."
    )
    if "no change" in message.lower():
        return {"reply": f"Offline {agent} reply: understood, nothing to change.", "edits": []}
    one_liner = f"{title}, focused on: {message}"[:300]
    return {
        "reply": reply,
        "edits": [
            {"op": "replace", "path": "/opportunity/one_liner", "value_json": json.dumps(one_liner)}
        ],
    }


def _merge(text: str) -> dict[str, Any]:
    sources = _briefs(text)
    titles = " + ".join(str(o["title"]) for o in sources)
    signals = [s for o in sources for s in o["signals"]]
    unique = list({s["url"]: s for s in signals}.values())[:6]
    first = sources[0]
    return {
        "title": f"Hybrid: {titles}"[:120],
        "one_liner": f"One product combining {titles}"[:300],
        "problem": " ".join(str(o["problem"]) for o in sources)[:800],
        "target_customer": first["target_customer"],
        "industry": first["industry"],
        "business_model": first["business_model"],
        "signals": unique,
        "novelty_score": max(int(o["novelty_score"]) for o in sources),
        "signal_strength": max(int(o["signal_strength"]) for o in sources),
        "is_generic": False,
    }


def offline_responder(request: LLMRequest[BaseModel], messages: Sequence[ChatMessage]) -> Scripted:
    """Plausible, schema-valid answers derived only from the prompt. Used by
    `LLM_PROVIDER=fake` outside tests so the CLI runs end-to-end without a network."""
    text = _user_text(messages)
    match request.agent:
        case "scout.plan":
            return _plan(text)
        case "scout.extract":
            target = re.search(r"up to (\d+) candidates", request.system)
            return _extract(text, int(target.group(1)) if target else 10)
        case "analyst":
            return _analysis(text)
        case "skeptic":
            return _critique(text)
        case "scout.merge":
            return _merge(text)
        case "cowork.scout" | "cowork.analyst" | "cowork.skeptic":
            return _cowork(request.agent.removeprefix("cowork."), text)
    raise LookupError(f"offline responder has no rule for agent {request.agent!r}")
