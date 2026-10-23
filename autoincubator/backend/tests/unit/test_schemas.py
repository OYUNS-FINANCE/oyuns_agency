from typing import Any

import pytest
from pydantic import ValidationError

from app.agents.analyst.schemas import MarketAnalysisOutput, SourcedFigure
from app.agents.common.schemas import RunInput
from app.agents.skeptic.schemas import RUBRIC_DIMENSIONS, CritiqueOutput
from tests import factories as f


class TestSourcedFigure:
    def test_accepts_source_url(self) -> None:
        fig = SourcedFigure(value=10, unit="USD", source_url=f.MARKET_URL)
        assert not fig.is_estimate

    def test_accepts_assumption(self) -> None:
        fig = SourcedFigure(value=10, unit="USD", assumption="100 clinics x $0.10")
        assert fig.is_estimate

    @pytest.mark.parametrize("assumption", [None, "", "   "])
    def test_rejects_figure_without_source_or_assumption(self, assumption: str | None) -> None:
        with pytest.raises(ValidationError, match="source_url or an explicit assumption"):
            SourcedFigure(value=10, unit="USD", assumption=assumption)

    def test_rejects_non_http_source(self) -> None:
        with pytest.raises(ValidationError):
            SourcedFigure(value=10, unit="USD", source_url="ftp://files.example/x")

    def test_rejects_negative_value(self) -> None:
        with pytest.raises(ValidationError):
            SourcedFigure(value=-1, unit="USD", assumption="x")


def _analysis_dict() -> dict[str, Any]:
    return f.analysis().model_dump()


@pytest.mark.parametrize(
    "path",
    [
        ("sizing", "tam"),
        ("sizing", "sam"),
        ("sizing", "som"),
        ("competitors", 0, "price"),
        ("pricing_benchmarks", 0, "price"),
    ],
)
def test_every_figure_in_an_analysis_needs_a_source_or_assumption(path: tuple[Any, ...]) -> None:
    data = _analysis_dict()
    node: Any = data
    for key in path:
        node = node[key]
    node["source_url"] = None
    node["assumption"] = None
    with pytest.raises(ValidationError, match="source_url or an explicit assumption"):
        MarketAnalysisOutput.model_validate(data)


def test_valid_analysis_has_only_sourced_or_assumed_figures() -> None:
    figures = f.analysis().figures()
    assert len(figures) == 5
    assert all(fig.source_url is not None or fig.assumption for fig in figures)


def test_market_sizing_must_nest() -> None:
    data = _analysis_dict()
    data["sizing"]["som"]["value"] = data["sizing"]["tam"]["value"] * 2
    with pytest.raises(ValidationError, match="SOM <= SAM <= TAM"):
        MarketAnalysisOutput.model_validate(data)


def test_run_input_mode_rules() -> None:
    assert RunInput(mode="seeded", seed="dental clinics").seed == "dental clinics"
    with pytest.raises(ValidationError, match="requires a seed"):
        RunInput(mode="seeded")
    with pytest.raises(ValidationError, match="takes no seed"):
        RunInput(mode="autonomous", seed="dental clinics")


def test_critique_needs_each_dimension_exactly_once() -> None:
    data = f.critique().model_dump()
    data["scores"][1]["dimension"] = data["scores"][0]["dimension"]
    with pytest.raises(ValidationError, match="exactly once"):
        CritiqueOutput.model_validate(data)
    assert len(f.critique().score_map()) == len(RUBRIC_DIMENSIONS)


def test_rubric_scores_are_bounded() -> None:
    data = f.critique().model_dump()
    data["scores"][0]["score"] = 11
    with pytest.raises(ValidationError):
        CritiqueOutput.model_validate(data)
