"""Deterministic offline search over JSON fixtures."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel

from app.providers.search.base import SearchResult

FIXTURES = Path(__file__).parent / "fixtures" / "results.json"
_WORD = re.compile(r"[a-z0-9]+")


class _Fixture(BaseModel):
    title: str
    url: str
    snippet: str
    keywords: list[str]


class MockSearchProvider:
    """Ranks fixtures by keyword overlap with the query; ties break on a stable hash.

    The fixtures deliberately include a prompt-injection page so tests exercise the
    untrusted-content handling.
    """

    def __init__(self, fixtures_path: Path = FIXTURES):
        raw = json.loads(fixtures_path.read_text(encoding="utf-8"))
        self._fixtures = [_Fixture.model_validate(item) for item in raw]
        self.queries: list[str] = []

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.queries.append(query)
        words = set(_WORD.findall(query.lower()))

        def rank(fx: _Fixture) -> tuple[int, str]:
            overlap = len(words & set(fx.keywords))
            tiebreak = hashlib.sha256(f"{query}|{fx.url}".encode()).hexdigest()
            return (-overlap, tiebreak)

        ranked = sorted(self._fixtures, key=rank)
        return [
            SearchResult.model_validate(fx.model_dump(exclude={"keywords"}))
            for fx in ranked[:max_results]
        ]
