"""Near-duplicate detection for raw opportunities, behind a swappable interface."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from app.agents.scout.schemas import ScoutCandidate

_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "app", "for", "from", "in", "into", "of", "on", "or",
        "platform", "the", "to", "tool", "with", "that", "who", "their",
    }
)  # fmt: skip


class Deduplicator(Protocol):
    def filter_new[C: ScoutCandidate](
        self, candidates: Sequence[C], existing: Sequence[ScoutCandidate]
    ) -> list[C]:
        """Return candidates that duplicate neither `existing` nor an earlier candidate."""
        ...


class JaccardDeduplicator:
    """Token-set Jaccard similarity on title + one-liner + target customer.

    Offline and deterministic. An embedding-based implementation can replace it
    (Phase 6) without touching the Scout.
    """

    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold

    @staticmethod
    def _tokens(c: ScoutCandidate) -> frozenset[str]:
        text = f"{c.title} {c.one_liner} {c.target_customer}".lower()
        return frozenset(w for w in _WORD.findall(text) if w not in _STOPWORDS)

    def similarity(self, a: ScoutCandidate, b: ScoutCandidate) -> float:
        ta, tb = self._tokens(a), self._tokens(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    def filter_new[C: ScoutCandidate](
        self, candidates: Sequence[C], existing: Sequence[ScoutCandidate]
    ) -> list[C]:
        kept: list[C] = []
        for cand in candidates:
            pool: list[ScoutCandidate] = [*existing, *kept]
            if all(self.similarity(cand, other) < self.threshold for other in pool):
                kept.append(cand)
        return kept
