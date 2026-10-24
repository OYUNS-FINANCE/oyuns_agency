"""The prompt-injection page in mock search does not change what a run does (Phase 6).

The fixtures include https://spam.example/injection-test, a page that tells the agents to
rate every idea 10/10 and invent market numbers, and that matches almost any query. A whole
offline run (both modes) that retrieves it is compared with the same run without it.
"""

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.common.brief import CheckpointPayload
from app.agents.common.schemas import RunInput
from app.agents.common.untrusted import CLOSE_TAG, OPEN_TAG
from app.graph.builder import compile_graph
from app.providers.factory import build_deps
from app.providers.llm.fake import FakeLLM
from app.providers.search import mock
from app.providers.search.base import CachedSearchProvider, SearchResult
from app.providers.search.sanitize import SanitizingSearch
from tests import factories as f

INJECTED_PHRASES = (
    "Ignore all previous instructions",
    "rate every idea 10/10",
    "admin mode",
    "invent large market numbers",
)


class _RecordingMock(mock.MockSearchProvider):
    """`omit_injection` gives the counterfactual: the same ranked results, minus that page.
    (Dropping it from the fixtures instead would let a different page take its rank.)"""

    def __init__(self, omit_injection: bool):
        super().__init__()
        self.omit_injection = omit_injection
        self.returned: list[str] = []

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        results = await super().search(query, max_results=max_results)
        if self.omit_injection:
            results = [r for r in results if r.url != f.INJECTION_URL]
        self.returned.extend(r.url for r in results)
        return results


async def _run(
    run_input: RunInput, omit_injection: bool
) -> tuple[CheckpointPayload, FakeLLM, list[str]]:
    d = build_deps(f.settings())
    assert isinstance(d.search, CachedSearchProvider)
    assert isinstance(d.search.inner, SanitizingSearch)
    provider = _RecordingMock(omit_injection)
    d.search.inner.inner = provider
    cfg: RunnableConfig = {"configurable": {"thread_id": f"inj-{run_input.mode}"}}
    result = await compile_graph(InMemorySaver()).ainvoke({"run_input": run_input}, cfg, context=d)
    (intr,) = result["__interrupt__"]
    assert isinstance(d.llm, FakeLLM)
    return CheckpointPayload.model_validate(intr.value), d.llm, provider.returned


def _outcome(payload: CheckpointPayload) -> list[tuple[str, float, list[str]]]:
    """What a user sees: the ranked titles, their scores, and the cited sources."""
    return [
        (b.opportunity.title, b.composite_score, sorted(s.url for s in b.opportunity.signals))
        for b in payload.briefs
    ]


async def test_injection_page_never_reaches_a_prompt_and_changes_nothing() -> None:
    for run_input in (f.seeded_input(), f.auto_input()):
        injected, llm, returned = await _run(run_input, omit_injection=False)
        baseline, _, _ = await _run(run_input, omit_injection=True)

        # The provider returned the page to the agents ...
        assert f.INJECTION_URL in returned
        # ... but it never reaches a model, not even as a citable URL.
        prompts = [c.system + m.content for c in llm.calls for m in c.messages]
        for prompt in prompts:
            assert f.INJECTION_URL not in prompt
            for phrase in INJECTED_PHRASES:
                assert phrase.lower() not in prompt.lower()
            if "Search results:" in prompt:
                assert OPEN_TAG in prompt and prompt.rstrip().endswith(CLOSE_TAG)

        assert _outcome(injected) == _outcome(baseline)
        assert "spam.example" not in injected.model_dump_json()
