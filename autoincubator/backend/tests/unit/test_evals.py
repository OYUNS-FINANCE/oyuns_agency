"""The manual evals' own logic, offline: collection, fetch classification, judging, metrics."""

import httpx
import pytest

from app.providers.llm.fake import FakeLLM
from app.providers.search.sanitize import strip_markup, tidy
from tests import factories as f
from tests.evals import collect, diversity, grounding, quality
from tests.evals.common import CollectedRun

PAGE = (
    "<html><body><h1>Vet clinics report</h1><p>"
    + "Background text about the veterinary sector. " * 20
    + "There are 32,000 independent clinics in the US, and the market is worth $4.2 billion."
    + "</p></body></html>"
)


async def _collected(name: str = "a01-test", auto: bool = False) -> CollectedRun:
    run_input = f.auto_input() if auto else f.seeded_input()
    return await collect.collect_one(name, run_input, f.settings(), collect.Spend(10.0))


async def test_collect_records_briefs_usage_and_searches() -> None:
    run = await _collected()
    assert run.error is None and run.checkpoint is not None and run.checkpoint.briefs
    assert run.searches > 0
    assert {u.agent for u in run.usage} >= {"scout.plan", "analyst", "skeptic"}
    assert CollectedRun.model_validate_json(run.model_dump_json()) == run


async def test_collect_stops_at_the_spend_limit() -> None:
    spend = collect.Spend(0.0)
    run = await collect.collect_one("a01", f.seeded_input(), f.settings(), spend)
    assert run.checkpoint is None and run.error and "SpendLimitError" in run.error


def test_run_inputs_reads_seeds_and_adds_autonomous_runs() -> None:
    inputs = collect.run_inputs(collect.SEEDS, only=2, autonomous=3)
    assert [n[:3] for n, _ in inputs] == ["a01", "a02", "b01", "b02", "b03"]
    assert inputs[0][1].seed == "independent veterinary clinics"
    assert inputs[0][1].constraints.business_model == "b2b"
    assert len(collect.run_inputs(collect.SEEDS, only=None, autonomous=0)) == 10


async def test_population_has_only_sourced_figures_with_labels() -> None:
    claims = grounding.population([await _collected()])
    assert claims
    assert all(c.url.startswith("http") for c in claims)
    assert len({(c.url, c.value, c.unit) for c in claims}) == len(claims)
    assert grounding.sample(claims, 2, seed=1) == grounding.sample(claims, 2, seed=1)


def _client(status: int = 200, body: str = PAGE, ctype: str = "text/html") -> httpx.AsyncClient:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body, headers={"content-type": ctype})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("status", "body", "ctype", "expected"),
    [
        (200, PAGE, "text/html; charset=utf-8", "ok"),
        (404, "", "text/html", "dead_link"),
        (403, "", "text/html", "blocked"),
        (500, "", "text/html", "http_error"),
        (200, "%PDF-1.7", "application/pdf", "unreadable"),
        (200, "<p>Please enable JavaScript to continue.</p>", "text/html", "blocked"),
    ],
)
async def test_fetch_classifies_pages(status: int, body: str, ctype: str, expected: str) -> None:
    async with _client(status, body, ctype) as client:
        page = await grounding.fetch(client, "https://x.example/a", 100_000)
    assert page.status == expected
    if expected == "ok":
        assert "32,000 independent clinics" in page.text and "<p>" not in page.text


async def test_fetch_reports_a_dead_host() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name not resolved", request=req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await grounding.fetch(client, "https://gone.example", 1000)
    assert page.status == "dead_link"


def test_number_tokens_and_excerpt_keep_the_number_in_a_long_page() -> None:
    assert {"4,200,000,000", "4.2"} <= grounding.number_tokens(4_200_000_000)
    assert "12" in grounding.number_tokens(0.12)
    filler = "lorem ipsum dolor sit amet " * 2_000
    text = filler + " the market is worth $4.2 billion in 2026 " + filler
    out = grounding.excerpt(text, 4_200_000_000)
    assert len(out) <= grounding.MAX_PAGE_CHARS + 50
    assert "$4.2 billion" in out
    assert grounding.excerpt("short page", 1.0) == "short page"


def _judgement(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "verdict": "supported",
        "cause": "none",
        "quote": "32,000 independent clinics in the US",
        "reasoning": "States the figure.",
    }
    return base | kw


async def test_the_judge_must_quote_the_page_verbatim() -> None:
    claim = grounding.Claim("r", "opp-01", "Vets", "segment size", 32_000, "clinics", "https://x")
    text = tidy(strip_markup(PAGE))
    llm = FakeLLM({"eval.grounding": [_judgement(quote="40,000 clinics"), _judgement()]})
    j, usage = await grounding.judge(llm, "m", claim, text)
    assert j.verdict == "supported" and len(usage) == 2
    assert "<source_page>" in llm.calls[0].messages[0].content


def test_judgement_cause_must_match_the_verdict() -> None:
    with pytest.raises(ValueError, match="cause"):
        grounding.GroundingJudgement.model_validate(_judgement(cause="wrong_number"))
    with pytest.raises(ValueError, match="quote"):
        grounding.GroundingJudgement.model_validate(
            _judgement(verdict="partial", cause="derived", quote="")
        )


async def test_evaluate_counts_unreadable_pages_as_failures() -> None:
    claims = [
        grounding.Claim("r", "opp-01", "Vets", "segment size", 32_000, "clinics", "https://ok"),
        grounding.Claim("r", "opp-01", "Vets", "TAM", 9e9, "USD", "https://dead"),
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "dead":
            return httpx.Response(404)
        return httpx.Response(200, text=PAGE, headers={"content-type": "text/html"})

    llm = FakeLLM({"eval.grounding": [_judgement()]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items, _ = await grounding.evaluate(claims, llm, "m", f.settings(), client)
    summary = grounding.summarise(items)
    assert summary["supported_pct"] == 50.0
    assert summary["supported_pct_of_readable"] == 100.0
    assert summary["failure_causes"] == {"dead_link": 1}
    assert "dead_link" in grounding.report(summary, items)


def _grade(score: int) -> dict[str, object]:
    g = {"score": score, "justification": "Because."}
    return {
        **{d: g for d in quality.DIMENSIONS},
        "worth_a_week": score >= 4,
        "verdict": "Fine idea.",
    }


async def test_quality_grades_top_briefs_and_averages_by_mode() -> None:
    runs = [await _collected("a01"), await _collected("b01", auto=True)]
    assert all(r.checkpoint and len(r.checkpoint.briefs) >= 2 for r in runs)
    llm = FakeLLM({"eval.quality": [_grade(4), _grade(2), _grade(5), _grade(3)]})
    grades, usage = await quality.evaluate(runs, llm, "m", top=2, concurrency=1)
    assert len(grades) == 4 and len(usage) == 4
    summary = quality.summarise(grades, runs)
    means = summary["means"]
    assert isinstance(means, dict) and means["overall"] == 3.5 and means["worth_a_week_pct"] == 50
    assert "<idea_brief>" in llm.calls[0].messages[0].content
    assert "| a01 |" in quality.report(summary, grades)


def test_diversity_separates_within_and_across_runs() -> None:
    items = [("b01", "A", "a"), ("b01", "B", "b"), ("b02", "C", "c")]
    vectors = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.01]]
    out = diversity.spread(items, vectors)
    assert out["mean_distance_within_run"] == 1.0
    assert out["min_distance_across_runs"] == 0.0
    dupes = out["near_duplicates_across_runs"]
    assert isinstance(dupes, list) and len(dupes) == 1 and dupes[0]["a"] == "b01: A"


async def test_diversity_uses_autonomous_briefs_only() -> None:
    runs = [await _collected("a01"), await _collected("b01", auto=True)]
    items = diversity.ideas(runs)
    assert items and {run for run, _, _ in items} == {"b01"}
