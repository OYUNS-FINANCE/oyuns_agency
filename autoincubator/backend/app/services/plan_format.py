"""Number formatting shared by the Editor's key-figures block and the dossier templates."""

from __future__ import annotations

import re


def money(v: float | None) -> str:
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    v = abs(v)
    return f"{sign}${v:,.0f}" if v >= 100 else f"{sign}${v:,.2f}"


def pct(v: float | None) -> str:
    """A fraction as a percentage: 0.05 → "5.0%"."""
    return "n/a" if v is None else f"{v * 100:.1f}%"


def num(v: float | None, decimals: int = 1) -> str:
    return "n/a" if v is None else f"{v:,.{decimals}f}"


def ratio(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}x"


def month(v: int | None) -> str:
    return "not within 12 months" if v is None else f"month {v}"


def figure(value: float, unit: str) -> str:
    """A SourcedFigure's value, formatted by its unit: money, a share, or a count."""
    u = unit.lower()
    if "share" in u or "fraction" in u:
        return pct(value)
    if "usd" in u or "$" in u:
        return money(value)
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def cell(text: str | None) -> str:
    """Text safe inside a Markdown table cell: one line, pipes escaped."""
    return " ".join((text or "").split()).replace("|", "\\|")


_BLOCK_START = re.compile(r"^(#|>|[-*+]\s|\d+[.)]\s)")


def inline(text: str | None) -> str:
    """Untrusted prose as one Markdown paragraph: no line breaks, and a leading heading,
    quote or list marker is escaped so it renders as text."""
    flat = " ".join((text or "").split())
    return "\\" + flat if _BLOCK_START.match(flat) else flat
