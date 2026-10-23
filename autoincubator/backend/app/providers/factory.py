"""Builds graph dependencies from settings (LLM_PROVIDER / SEARCH_PROVIDER)."""

from __future__ import annotations

from anthropic import AsyncAnthropic

from app.core.config import Settings
from app.events.sink import EventSink, NullEventSink
from app.graph.deps import GraphDeps
from app.providers.dedup import JaccardDeduplicator
from app.providers.llm.anthropic import AnthropicLLM
from app.providers.llm.base import BeforeCallHook, LLMProvider, UsageHook
from app.providers.llm.fake import FakeLLM, offline_responder
from app.providers.search.base import CachedSearchProvider, SearchCache, SearchHook
from app.providers.search.mock import MockSearchProvider


def build_llm(
    settings: Settings,
    usage_hook: UsageHook | None = None,
    before_call: BeforeCallHook | None = None,
) -> LLMProvider:
    if settings.llm_provider == "fake":
        return FakeLLM(
            responder=offline_responder,
            max_validation_retries=settings.llm_max_validation_retries,
            usage_hook=usage_hook,
            before_call=before_call,
            latency_s=settings.fake_llm_latency_ms / 1000,
        )
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
    # Empty → let the SDK resolve credentials itself (ANTHROPIC_API_KEY, profiles, WIF).
    client = AsyncAnthropic(api_key=key) if key else AsyncAnthropic()
    return AnthropicLLM(
        client,
        max_validation_retries=settings.llm_max_validation_retries,
        usage_hook=usage_hook,
        before_call=before_call,
    )


def build_deps(
    settings: Settings,
    usage_hook: UsageHook | None = None,
    *,
    before_call: BeforeCallHook | None = None,
    search_cache: SearchCache | None = None,
    before_search: SearchHook | None = None,
    after_search: SearchHook | None = None,
    events: EventSink | None = None,
) -> GraphDeps:
    """One GraphDeps per run: the search cache and budget hooks are scoped to it."""
    return GraphDeps(
        llm=build_llm(settings, usage_hook, before_call),
        search=CachedSearchProvider(
            MockSearchProvider(),
            search_cache,
            before_search=before_search,
            after_search=after_search,
        ),
        dedup=JaccardDeduplicator(settings.dedup_threshold),
        settings=settings,
        events=events or NullEventSink(),
    )
