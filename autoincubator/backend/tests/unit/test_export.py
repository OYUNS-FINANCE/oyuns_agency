"""Dossier export: every number traces (acceptance check), Markdown safety, PDF rendering."""

from __future__ import annotations

import builtins
import re
import sys
from datetime import date
from typing import Any

import pytest

from app.agents.common.schemas import RunInput
from app.agents.editor.schemas import BusinessPlan
from app.services.export import pdf
from app.services.export.markdown import render_markdown, undisclosed_untraced
from app.services.plan_trace import plan_registry
from app.services.trace import untraced_in
from tests import factories as f

DAY = date(2026, 10, 23)


def _pango_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except OSError:
        return False
    return True


# On macOS the uv-managed Python only finds Homebrew's Pango with
# DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib (the Makefile sets it). Elsewhere a missing
# Pango is a real failure.
needs_pango = pytest.mark.skipif(
    sys.platform == "darwin" and not _pango_available(),
    reason="Pango not loadable: run with DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib",
)


async def test_every_number_in_the_dossier_traces_to_a_source_assumption_or_engine() -> None:
    plan = await f.business_plan()
    markdown = render_markdown(plan, 1, DAY)
    assert untraced_in([markdown], plan_registry(plan)) == []
    # The check is not vacuous: the dossier is full of numbers, and an invented one is caught.
    assert markdown.count("$") > 100
    assert undisclosed_untraced(plan, markdown + "\nRevenue will reach $987,654.\n") == ["$987,654"]


async def test_changing_an_assumption_changes_the_dossier_numbers_consistently() -> None:
    cheap = await f.business_plan()
    rich_founder = RunInput.model_validate(
        {"mode": "seeded", "seed": "small service businesses",
         "founder_profile": {"capital_usd": 90_000}}
    )  # fmt: skip
    rich = await f.business_plan(run_input=rich_founder)
    assert rich.assumptions.starting_cash.value == 90_000
    md = render_markdown(rich, 1, DAY)
    assert "$90,000" in md and undisclosed_untraced(rich, md) == []
    assert rich.financials.base.months[-1].cash - cheap.financials.base.months[-1].cash == (
        pytest.approx(90_000 - 25_000)
    )


async def test_untraced_brief_numbers_are_disclosed_in_the_dossier() -> None:
    brief = f.idea_brief(problem="Clinics lose 37% of their slots to no-shows every month.")
    plan = await f.business_plan(brief)
    (c,) = [c for c in plan.contradictions if c.code == "untraced_number"]
    assert c.untraced == ["37%"]
    markdown = render_markdown(plan, 1, DAY)
    assert "Unverified: `37%`" in markdown
    assert undisclosed_untraced(plan, markdown) == []  # flagged, so not hidden


async def test_dossier_has_every_section_and_the_appendix() -> None:
    plan = await f.business_plan()
    markdown = render_markdown(plan, 1, DAY)
    for heading in (
        "## 1. Executive summary",
        "## 2. The opportunity",
        "## 3. Product",
        "## 4. Go-to-market",
        "## 5. Financials",
        "### 12-month projection: base case",
        "### 12-month projection: bear case",
        "### 12-month projection: bull case",
        "## 6. Contradictions & open questions",
        "## 7. Risks",
        "## 8. 30/60/90-day launch checklist",
        "## Appendix: Sources & Assumptions",
        "### Engine calculations",
    ):
        assert heading in markdown
    for item in plan.checklist.day_30 + plan.checklist.day_60 + plan.checklist.day_90:
        assert f"- [ ] {item}" in markdown
    assert f"<{f.DENTAL_URL}>" in markdown and f.MARKET_URL in markdown


async def test_model_text_cannot_break_tables_or_inject_blocks() -> None:
    brief = f.idea_brief(
        problem="# Fake heading\n\n| injected | row |",
        target_customer="Owners | with pipes",
    )
    plan = await f.business_plan(brief)
    data = plan.model_dump(mode="json")
    data["product"]["stack"][0]["why"] = "Fast | cheap\nand easy"
    markdown = render_markdown(BusinessPlan.model_validate(data), 1, DAY)
    assert "\n# Fake heading" not in markdown
    assert "**Problem.** \\# Fake heading | injected | row |" in markdown
    assert "| Fast \\| cheap and easy |" in markdown


def test_raw_html_in_the_markdown_is_not_rendered() -> None:
    out = pdf.markdown_to_html("Hello <script>alert(1)</script> <img src=x>", "T")
    assert "<script>" not in out and "<img" not in out
    assert "&lt;script&gt;" in out


@needs_pango
async def test_pdf_renders_with_the_bundled_font_and_cyrillic_text() -> None:
    brief = f.idea_brief(title="Шүдний эмнэлгийн сануулга", target_customer="Өрхийн эмнэлгүүд")
    plan = await f.business_plan(brief)
    body = pdf.render_pdf(render_markdown(plan, 1, DAY), brief.opportunity.title, compress=False)
    assert body.startswith(b"%PDF-")
    # Only the bundled fonts are embedded: no fallback font was needed for any glyph.
    names = set(re.findall(rb"/BaseFont /[A-Z]{6}\+([\w-]+)", body))
    assert names and all(n.startswith(b"Noto-Sans") for n in names), names
    assert len(re.findall(rb"/Type\s*/Page(?![s\w])", body)) >= 8  # sections break pages


@needs_pango
def test_pdf_rendering_fetches_nothing_but_the_bundled_fonts() -> None:
    import weasyprint

    fetcher = pdf._fetcher(weasyprint)
    assert fetcher.fetch(f"{pdf.FONTS.as_uri()}/NotoSans-Regular.ttf") is not None
    for url in (
        "http://127.0.0.1:9/x.png",
        "https://example.com/a.css",
        "file:///etc/passwd",
        f"{pdf.FONTS.as_uri()}/../../../core/config.py",
    ):
        with pytest.raises(ValueError, match=r"blocked resource|disallowed protocol"):
            fetcher.fetch(url)
    # A remote image in model text does not stall or fail the render.
    assert pdf.render_pdf("![x](http://127.0.0.1:9/evil.png)\n\nText", "T").startswith(b"%PDF")


def test_missing_pango_is_a_clear_503(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "weasyprint":
            raise OSError("cannot load library 'libgobject-2.0-0'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "weasyprint", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(pdf.PdfUnavailableError) as exc:
        pdf.render_pdf("# x", "T")
    assert exc.value.status_code == 503 and exc.value.code == "pdf_unavailable"
