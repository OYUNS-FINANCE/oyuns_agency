"""RunBudget: warning at 80% (once), exhaustion at 100% before the next call."""

import asyncio

import pytest

from app.agents.scout.schemas import ScoutQueryPlan
from app.events.schema import BudgetExhausted, BudgetWarning
from app.events.sink import RecordingEventSink
from app.providers.llm.base import ChatMessage, LLMRequest, UsageRecord
from app.providers.llm.fake import FakeLLM
from app.providers.search.base import CachedSearchProvider
from app.providers.search.mock import MockSearchProvider
from app.services.budget import BudgetExhaustedError, RunBudget
from tests import factories as f


class MemoryStore:
    def __init__(self, tokens: int = 0, searches: int = 0):
        self.tokens = tokens
        self.searches = searches
        self.records: list[UsageRecord] = []
        self.spent_today = 0.0

    async def add_usage(self, usage: UsageRecord) -> int:
        self.records.append(usage)
        self.tokens += usage.input_tokens + usage.output_tokens
        return self.tokens

    async def add_search(self) -> int:
        self.searches += 1
        return self.searches

    async def spent_today_usd(self) -> float:
        return self.spent_today


def _budget(
    sink: RecordingEventSink, *, max_tokens: int = 100, max_searches: int = 10, **used: int
) -> tuple[RunBudget, MemoryStore]:
    store = MemoryStore(used.get("tokens", 0), used.get("searches", 0))
    budget = RunBudget(
        max_tokens=max_tokens,
        max_searches=max_searches,
        tokens_used=store.tokens,
        searches_used=store.searches,
        store=store,
        events=sink,
    )
    return budget, store


def _usage(tokens: int) -> UsageRecord:
    return UsageRecord(agent="scout.plan", model="m", input_tokens=tokens)


async def test_warns_once_at_80_percent_then_exhausts_at_the_cap() -> None:
    sink = RecordingEventSink()
    budget, _ = _budget(sink)
    await budget.before_llm_call("a")
    await budget.record_usage(_usage(50))
    assert sink.events == []
    await budget.record_usage(_usage(30))
    await budget.record_usage(_usage(10))
    assert sink.of_type(BudgetWarning) == [BudgetWarning(kind="tokens", used=80, limit=100)]

    await budget.before_llm_call("a")  # 90 < 100: still allowed
    await budget.record_usage(_usage(15))
    with pytest.raises(BudgetExhaustedError) as exc:
        await budget.before_llm_call("a")
    assert exc.value.event() == BudgetExhausted(kind="tokens", used=105, limit=100)
    with pytest.raises(BudgetExhaustedError):
        await budget.before_llm_call("a")
    # The worker records exhaustion with the final status; the budget itself only raises.
    assert sink.of_type(BudgetExhausted) == []


async def test_restart_past_threshold_does_not_warn_again() -> None:
    sink = RecordingEventSink()
    budget, _ = _budget(sink, tokens=85)
    await budget.record_usage(_usage(5))
    assert sink.of_type(BudgetWarning) == []


async def test_llm_retry_attempts_are_each_checked_and_recorded() -> None:
    sink = RecordingEventSink()
    budget, store = _budget(sink, max_tokens=1)
    llm = FakeLLM(
        {"scout.plan": ["not json", f.plan()]},
        usage_hook=budget.record_usage,
        before_call=budget.before_llm_call,
    )
    with pytest.raises(BudgetExhaustedError):
        await llm.generate(
            LLMRequest(
                agent="scout.plan",
                model="m",
                system="plan",
                messages=[ChatMessage(role="user", content="seed")],
                output_type=ScoutQueryPlan,
            )
        )
    assert len(store.records) == 1  # the retry was refused before reaching the provider
    assert len(llm.calls) == 1


async def test_search_budget_counts_cache_misses_only() -> None:
    sink = RecordingEventSink()
    budget, store = _budget(sink, max_searches=2)
    search = CachedSearchProvider(
        MockSearchProvider(),
        before_search=budget.before_search,
        after_search=budget.record_search,
    )
    await search.search("dental clinics")
    await search.search("  Dental   CLINICS ")  # same normalised query: cached, free
    assert store.searches == 1
    await search.search("hvac dispatch")
    assert sink.of_type(BudgetWarning) == [BudgetWarning(kind="searches", used=2, limit=2)]
    with pytest.raises(BudgetExhaustedError):
        await search.search("vet clinics")
    assert await search.search("dental clinics")  # cached results still served


async def test_usage_is_recorded_even_when_the_caller_is_cancelled() -> None:
    class SlowStore(MemoryStore):
        async def add_usage(self, usage: UsageRecord) -> int:
            await asyncio.sleep(0.05)
            return await super().add_usage(usage)

    sink = RecordingEventSink()
    store = SlowStore()
    budget = RunBudget(
        max_tokens=100, max_searches=1, tokens_used=0, searches_used=0, store=store, events=sink
    )
    task = asyncio.create_task(budget.record_usage(_usage(90)))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.1)
    assert store.tokens == 90
    assert sink.of_type(BudgetWarning) == [BudgetWarning(kind="tokens", used=90, limit=100)]


async def test_daily_cost_cap_stops_the_next_call_and_names_the_cap() -> None:
    sink = RecordingEventSink()
    store = MemoryStore()
    budget = RunBudget(
        max_tokens=100,
        max_searches=10,
        tokens_used=0,
        searches_used=0,
        store=store,
        events=sink,
        daily_cap_usd=5.0,
    )
    store.spent_today = 4.99
    await budget.before_llm_call("a")
    store.spent_today = 5.0
    with pytest.raises(BudgetExhaustedError) as exc:
        await budget.before_llm_call("a")
    assert exc.value.kind == "daily_cost"
    assert (exc.value.used, exc.value.limit) == (500, 500)
    assert "daily cost cap reached" in str(exc.value)
    assert exc.value.event() == BudgetExhausted(kind="daily_cost", used=500, limit=500)


async def test_daily_cap_of_zero_is_off() -> None:
    sink = RecordingEventSink()
    store = MemoryStore()
    store.spent_today = 10_000.0
    budget = RunBudget(
        max_tokens=100, max_searches=1, tokens_used=0, searches_used=0, store=store, events=sink
    )
    await budget.before_llm_call("a")
