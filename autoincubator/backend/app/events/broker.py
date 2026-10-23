"""One LISTEN connection per API process, fanned out to SSE streams as wake-ups. ADR 0003.

Notifications carry no data that streams rely on: they only say "run X has new events".
Streams always read the events themselves from agent_events, so a missed notification
costs latency (until the fallback poll), never correctness.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import AsyncIterator

import asyncpg

from app.core.logging import get_logger
from app.db.repositories.events import NOTIFY_CHANNEL

log = get_logger(__name__)


class EventBroker:
    def __init__(self, dsn: str, reconnect_interval_s: float = 5.0):
        self.dsn = dsn
        self.reconnect_interval_s = reconnect_interval_s
        self._subscribers: defaultdict[str, set[asyncio.Event]] = defaultdict(set)
        self._conn: asyncpg.Connection | None = None
        self._watchdog: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._conn is not None and not self._conn.is_closed()

    async def start(self) -> None:
        """Never raises: if Postgres is down, the watchdog keeps retrying."""
        await self._connect()
        self._watchdog = asyncio.create_task(self._watch())

    async def stop(self) -> None:
        if self._watchdog is not None:
            self._watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog
        if self._conn is not None and not self._conn.is_closed():
            await self._conn.close()

    async def _connect(self) -> None:
        try:
            conn: asyncpg.Connection = await asyncpg.connect(self.dsn)
            await conn.add_listener(NOTIFY_CHANNEL, self._on_notify)
        except Exception:
            log.warning("events.listen_connect_failed", exc_info=True)
            return
        self._conn = conn
        log.info("events.listening", channel=NOTIFY_CHANNEL)
        # Anything committed while we were disconnected: let every stream re-read.
        self._wake_all()

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(self.reconnect_interval_s)
            if not self.connected:
                await self._connect()

    def _on_notify(self, conn: object, pid: int, channel: str, payload: str) -> None:
        run_id = payload.split(":", 1)[0]
        for wake in self._subscribers.get(run_id, ()):
            wake.set()

    def _wake_all(self) -> None:
        for subs in self._subscribers.values():
            for wake in subs:
                wake.set()

    @contextlib.asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Event]:
        wake = asyncio.Event()
        self._subscribers[run_id].add(wake)
        try:
            yield wake
        finally:
            subs = self._subscribers[run_id]
            subs.discard(wake)
            if not subs:
                del self._subscribers[run_id]
