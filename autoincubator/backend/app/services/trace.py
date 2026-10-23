"""Number traceability: every number in the dossier must come from a source, a stated
assumption, or an engine calculation (CLAUDE.md: no invented numbers).

A `FigureRegistry` holds the numbers the plan may state. `untraced(text)` returns the
numbers in a text that match none of them. Matching is by value, with the tolerance the
text's own precision implies ("$1,234" matches 1234.4; "80%" matches 0.8). Numbers written
inside a stated assumption or a cited signal's evidence are registered too: they *are*
the assumption or the source.

Not checked: URLs, dates (ISO dates and bare years 1900-2099, such as a regulation's
deadline), inline code spans (the template quotes untraced tokens in them), and small
structural integers (counts, months 1-12, the 30/60/90 plan, "first 100 customers").
Trade-off: a bare four-digit count in that range ("2000 clinics") also passes as a year;
written with a comma, a currency or a unit suffix it is checked.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

TraceKind = Literal["source", "assumption", "estimate", "engine", "score"]

STRUCTURAL_INTEGERS = frozenset({*range(13), 30, 60, 90, 100})
_MULTIPLIERS = {"k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6, "mn": 1e6, "bn": 1e9, "B": 1e9}

_URL = re.compile(r"https?://[^\s)>\]]+")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+Z?)?\b")
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_NUMBER = re.compile(
    r"""(?<![\w.])                     # not glued to a word or another number
        (?<![^\W\d_]-)                  # nor an identifier such as opp-01 (ranges still count)
        (?P<sign>[-\u2212])?
        (?P<cur>[$€£₮])?
        (?P<int>\d{1,3}(?:,\d{3})+|\d+)
        (?P<frac>\.\d+)?
        (?:\s?(?P<mult>bn|mn|[kKmMB])(?![\w]))?
        (?P<pct>\s?%)?
        x?                             # a ratio such as 8.5x
        (?![\w])""",
    re.VERBOSE,
)


YEARS = range(1900, 2100)


@dataclass(frozen=True)
class NumberToken:
    raw: str
    value: float
    decimals: int
    is_percent: bool
    multiplier: float

    @property
    def is_structural(self) -> bool:
        if self.is_percent or self.multiplier != 1 or self.decimals or self.value < 0:
            return False
        plain = self.raw.isdigit()  # no currency sign or thousands separator
        return self.value in STRUCTURAL_INTEGERS or (plain and int(self.value) in YEARS)

    @property
    def tolerance(self) -> float:
        """Half a unit of the last written digit, scaled by any k/M suffix."""
        return 0.5 * 10.0 ** (-self.decimals) * self.multiplier


def extract_numbers(text: str) -> list[NumberToken]:
    text = _CODE_SPAN.sub(" ", _ISO_DATE.sub(" ", _URL.sub(" ", text)))
    out: list[NumberToken] = []
    for m in _NUMBER.finditer(text):
        digits = m["int"].replace(",", "") + (m["frac"] or "")
        mult = _MULTIPLIERS[m["mult"]] if m["mult"] else 1.0
        value = float(digits) * mult
        out.append(
            NumberToken(
                raw=m.group(0).strip(),
                value=-value if m["sign"] else value,
                decimals=len(m["frac"]) - 1 if m["frac"] else 0,
                is_percent=m["pct"] is not None,
                multiplier=mult,
            )
        )
    return out


@dataclass(frozen=True)
class TracedFigure:
    value: float
    kind: TraceKind
    label: str
    ref: str
    """A URL (source), the assumption text, or the engine formula."""


@dataclass
class FigureRegistry:
    figures: list[TracedFigure] = field(default_factory=list)

    def add(self, value: float | None, kind: TraceKind, label: str, ref: str) -> None:
        if value is not None and math.isfinite(value):
            self.figures.append(TracedFigure(value, kind, label, ref))

    def add_text(self, text: str | None, kind: TraceKind, label: str, ref: str) -> None:
        """Registers the numbers written inside an assumption or a source's evidence."""
        for token in extract_numbers(text or ""):
            self.add(token.value, kind, label, ref)
            if token.is_percent:
                self.add(token.value / 100, kind, label, ref)

    def extend(self, other: FigureRegistry) -> FigureRegistry:
        return FigureRegistry([*self.figures, *other.figures])

    def matches(self, token: NumberToken) -> bool:
        if token.is_structural:
            return True
        # (value as written, tolerance); "80%" may stand for 80 or for the fraction 0.8.
        candidates = [(abs(token.value), token.tolerance)]
        if token.is_percent:
            candidates.append((abs(token.value) / 100, token.tolerance / 100))
        return any(
            abs(abs(f.value) - c) <= tol + 1e-9 * max(1.0, c)
            for f in self.figures
            for c, tol in candidates
        )

    def untraced(self, text: str) -> list[str]:
        return [t.raw for t in extract_numbers(text) if not self.matches(t)]


def iter_strings(model: BaseModel, exempt: frozenset[str] = frozenset()) -> Iterator[str]:
    """Every string value in a model, skipping fields named in `exempt` at any depth."""

    def walk(value: object) -> Iterator[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for k, v in value.items():
                if k not in exempt:
                    yield from walk(v)
        elif isinstance(value, list):
            for v in value:
                yield from walk(v)

    yield from walk(model.model_dump(mode="json"))


def untraced_in(texts: Iterable[str], registry: FigureRegistry) -> list[str]:
    seen: dict[str, None] = {}
    for text in texts:
        for raw in registry.untraced(text):
            seen.setdefault(raw)
    return list(seen)
