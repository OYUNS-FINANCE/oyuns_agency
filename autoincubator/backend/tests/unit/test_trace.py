import pytest

from app.services.trace import FigureRegistry, extract_numbers


def _registry(*values: float) -> FigureRegistry:
    r = FigureRegistry()
    for v in values:
        r.add(v, "engine", "x", "formula")
    return r


@pytest.mark.parametrize(
    ("text", "value", "pct"),
    [
        ("$1,234.50", 1234.5, False),
        ("80%", 80, True),
        ("12.5 %", 12.5, True),
        ("€3.2M", 3_200_000, False),
        ("2 bn", 2e9, False),
        ("\u2212$3,040", -3040, False),
        ("₮150,000", 150_000, False),
        ("8.5x", 8.5, False),
    ],
)
def test_extracts_value_and_percent(text: str, value: float, pct: bool) -> None:
    (token,) = extract_numbers(f"Revenue is {text} today.")
    assert token.value == pytest.approx(value)
    assert token.is_percent is pct


def test_ignores_urls_dates_code_spans_and_identifiers() -> None:
    text = (
        "See https://news.example/2026/report-77 on 2026-10-23; idea opp-01 and `4711`, "
        "model v3, Q4."
    )
    assert extract_numbers(text) == []
    assert [t.value for t in extract_numbers("5-10 days, $500-2,000")] == [5, 10, 500, 2000]


def test_matches_with_the_precision_written() -> None:
    r = _registry(1234.4, 0.8, 59.5, 3_249_000.0, -3040.0)
    assert r.untraced("ARPA $1,234 at 80% margin, 59.5 customers") == []
    assert r.untraced("about $3.2M a year, burning $3,040") == []
    assert r.untraced("$1,240 and 81%") == ["$1,240", "81%"]


def test_structural_integers_are_allowed_but_not_as_percentages() -> None:
    r = _registry()
    assert r.untraced("first 100 customers in 30, 60 and 90 days; 3 features; month 12") == []
    assert r.untraced("12% of clinics and 13 features") == ["12%", "13"]
    assert r.untraced("required by 2027, since 1999") == []
    assert r.untraced("$2027, 2,027 and 2027.5") == ["$2027", "2,027", "2027.5"]


def test_numbers_inside_an_assumption_text_are_registered() -> None:
    r = FigureRegistry()
    r.add_text("4,000 clinics x $1,200/yr; 25% reachable", "assumption", "SAM", "note")
    assert r.untraced("4,000 clinics paying $1,200, a quarter (25%) reachable") == []
    assert r.untraced("0.25 of them") == []
