"""Per-run token and search budget. See ADR 0004.

Checked before every LLM attempt and every search-provider call (cache misses). At 80% of
a cap a `budget.warning` is emitted once; once a cap is reached the next call raises
BudgetExhaustedError. The worker then records `budget.exhausted`, `run.error` and the
`budget_exhausted` status in one transaction. (Emitting from here would race: parallel
siblings are cancelled as soon as one of them raises.)

Parallel calls that pass the check together may overshoot a cap by at most one call each
(bounded by AGENT_CONCURRENCY).
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from app.events.schema import BudgetExhausted, BudgetKind, BudgetWarning
from app.events.sink import EventSink
from app.providers.llm.base import UsageRecord

WARNING_RATIO = 0.8


class BudgetExhaustedError(RuntimeError):
    def __init__(self, kind: BudgetKind, used: int, limit: int):
        super().__init__(f"{kind} budget exhausted: used {used} of {limit}")
        self.kind: BudgetKind = kind
        self.used = used
        self.limit = limit

    def event(self) -> BudgetExhausted:
        return BudgetExhausted(kind=self.kind, used=self.used, limit=self.limit)


class UsageStore(Protocol):
    """Persists usage; each method returns the run's new running total."""

    async def add_usage(self, usage: UsageRecord) -> int: ...
    async def add_search(self) -> int: ...


class RunBudget:
    def __init__(
        self,
        *,
        max_tokens: int,
        max_searches: int,
        tokens_used: int,
        searches_used: int,
        store: UsageStore,
        events: EventSink,
    ):
        self.limits: dict[BudgetKind, int] = {"tokens": max_tokens, "searches": max_searches}
        self.used: dict[BudgetKind, int] = {"tokens": tokens_used, "searches": searches_used}
        self.store = store
        self.events = events
        # Already past the threshold (e.g. after a worker restart): the warning was sent.
        self._warned: set[BudgetKind] = {k for k in self.limits if self._over_warning(k)}

    def _over_warning(self, kind: BudgetKind) -> bool:
        return self.used[kind] >= WARNING_RATIO * self.limits[kind]

    async def _check(self, kind: BudgetKind) -> None:
        used, limit = self.used[kind], self.limits[kind]
        if used >= limit:
            raise BudgetExhaustedError(kind, used, limit)

    async def _record(self, kind: BudgetKind, total: int) -> None:
        self.used[kind] = total
        if kind not in self._warned and self._over_warning(kind):
            self._warned.add(kind)
            await self.events.emit(BudgetWarning(kind=kind, used=total, limit=self.limits[kind]))

    async def before_llm_call(self, agent: str) -> None:
        await self._check("tokens")

    async def record_usage(self, usage: UsageRecord) -> None:
        # Shielded: a sibling call hitting the cap cancels this task, but money already
        # spent must still be recorded.
        await asyncio.shield(self._add_usage(usage))

    async def _add_usage(self, usage: UsageRecord) -> None:
        await self._record("tokens", await self.store.add_usage(usage))

    async def before_search(self, query: str) -> None:
        await self._check("searches")

    async def record_search(self, query: str) -> None:
        await asyncio.shield(self._add_search())

    async def _add_search(self) -> None:
        await self._record("searches", await self.store.add_search())
