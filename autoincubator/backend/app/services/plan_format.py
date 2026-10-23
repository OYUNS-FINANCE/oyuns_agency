"""Number formatting shared by the Editor's key-figures block and the dossier templates."""

from __future__ import annotations


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
