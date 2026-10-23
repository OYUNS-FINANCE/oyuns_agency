"""Where graph nodes send events. Nodes never touch the database themselves."""

from __future__ import annotations

from typing import Protocol

from app.events.schema import EventData


class EventSink(Protocol):
    async def emit(self, data: EventData, *, agent: str | None = None) -> None: ...


class NullEventSink:
    """For the CLI and tests that do not care about events."""

    async def emit(self, data: EventData, *, agent: str | None = None) -> None:
        return None


class RecordingEventSink:
    """Keeps every event in memory, in order; for unit tests."""

    def __init__(self) -> None:
        self.events: list[tuple[str | None, EventData]] = []

    async def emit(self, data: EventData, *, agent: str | None = None) -> None:
        self.events.append((agent, data))

    def of_type[T: EventData](self, cls: type[T]) -> list[T]:
        return [d for _, d in self.events if isinstance(d, cls)]
