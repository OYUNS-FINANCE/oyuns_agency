"""Runtime dependencies injected into nodes via LangGraph's context (never checkpointed)."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.providers.dedup import Deduplicator
from app.providers.llm.base import LLMProvider
from app.providers.search.base import SearchProvider


@dataclass(frozen=True)
class GraphDeps:
    llm: LLMProvider
    search: SearchProvider
    dedup: Deduplicator
    settings: Settings
