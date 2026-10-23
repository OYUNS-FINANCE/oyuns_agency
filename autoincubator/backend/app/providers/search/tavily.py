"""Tavily search (https://docs.tavily.com/documentation/api-reference/endpoint/search)."""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import ValidationError

from app.providers.search.base import SearchResult
from app.providers.search.http import HttpSearchProvider

log = structlog.get_logger(__name__)


class TavilySearch(HttpSearchProvider):
    name = "tavily"
    url = "https://api.tavily.com/search"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _body(self, query: str, max_results: int) -> dict[str, Any]:
        return {
            "query": query,
            "max_results": max(1, min(20, max_results)),
            "search_depth": "basic",
            "topic": "general",
            "include_answer": False,
            "include_raw_content": False,
        }

    def _parse(self, payload: dict[str, Any]) -> list[SearchResult]:
        out: list[SearchResult] = []
        for item in payload.get("results") or []:
            try:
                out.append(
                    SearchResult(
                        title=str(item.get("title") or ""),
                        url=str(item.get("url") or ""),
                        snippet=str(item.get("content") or ""),
                        published=item.get("published_date") or None,
                    )
                )
            except ValidationError:
                log.warning("search.bad_result", provider=self.name, url=item.get("url"))
        return out
