"""Serper search: Google results (https://serper.dev)."""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import ValidationError

from app.providers.search.base import SearchResult
from app.providers.search.http import HttpSearchProvider

log = structlog.get_logger(__name__)


class SerperSearch(HttpSearchProvider):
    name = "serper"
    url = "https://google.serper.dev/search"

    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self._api_key, "Content-Type": "application/json"}

    def _body(self, query: str, max_results: int) -> dict[str, Any]:
        return {"q": query, "num": max(1, min(100, max_results))}

    def _parse(self, payload: dict[str, Any]) -> list[SearchResult]:
        out: list[SearchResult] = []
        for item in payload.get("organic") or []:
            try:
                out.append(
                    SearchResult(
                        title=str(item.get("title") or ""),
                        url=str(item.get("link") or ""),
                        snippet=str(item.get("snippet") or ""),
                        published=item.get("date") or None,
                    )
                )
            except ValidationError:
                log.warning("search.bad_result", provider=self.name, url=item.get("link"))
        return out
