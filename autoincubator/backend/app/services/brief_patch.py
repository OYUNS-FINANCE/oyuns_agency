"""JSON Patch (RFC 6902 add/replace/remove) against an idea brief, with the brief's rules.

A patch may edit the opportunity and the market analysis, never the critique (that changes
only through a re-score) or the ids. The patched brief must re-validate against the agent
schemas, so every figure still carries a `source_url` or an `assumption`; and it may cite
only URLs the idea already cites, because co-working has no search tool (ADR 0006).
"""

from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.agents.analyst.schemas import MarketAnalysis
from app.agents.scout.schemas import RawOpportunity

PatchOpName = Literal["add", "replace", "remove"]
EDITABLE_ROOTS = ("opportunity", "analysis")
LOCKED_PATHS = frozenset({"/opportunity/id", "/opportunity/iteration", "/analysis/opportunity_id"})


class PatchOperation(BaseModel):
    op: PatchOpName
    path: str
    value: Any = None


class PatchError(ValueError):
    """The patch does not apply, or the result breaks the brief's rules."""


class EditableBrief(BaseModel):
    """The part of an idea version a patch may change."""

    opportunity: RawOpportunity
    analysis: MarketAnalysis


def _tokens(path: str) -> list[str]:
    if not path.startswith("/"):
        raise PatchError(f"path {path!r} must start with '/'")
    tokens = [t.replace("~1", "/").replace("~0", "~") for t in path[1:].split("/")]
    if len(tokens) < 2 or tokens[0] not in EDITABLE_ROOTS:
        raise PatchError(
            f"path {path!r} must point inside /opportunity or /analysis (the critique changes "
            "only through a re-score)"
        )
    if path in LOCKED_PATHS:
        raise PatchError(f"path {path!r} is read-only")
    return tokens


def _index(container: list[Any], token: str, *, allow_end: bool) -> int:
    if allow_end and token == "-":
        return len(container)
    if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
        raise PatchError(f"{token!r} is not a list index")
    i = int(token)
    if i > len(container) or (i == len(container) and not allow_end):
        raise PatchError(f"list index {i} is out of range")
    return i


def _parent(doc: Any, tokens: list[str], path: str) -> Any:
    node = doc
    for token in tokens[:-1]:
        if isinstance(node, dict):
            if token not in node:
                raise PatchError(f"path {path!r} does not exist")
            node = node[token]
        elif isinstance(node, list):
            node = node[_index(node, token, allow_end=False)]
        else:
            raise PatchError(f"path {path!r} goes through a value that is not a container")
    return node


def _apply_one(doc: dict[str, Any], op: PatchOperation) -> None:
    tokens = _tokens(op.path)
    parent = _parent(doc, tokens, op.path)
    last = tokens[-1]
    if isinstance(parent, dict):
        if op.op == "add":
            parent[last] = op.value
        elif last not in parent:
            raise PatchError(f"path {op.path!r} does not exist")
        elif op.op == "replace":
            parent[last] = op.value
        else:
            del parent[last]
    elif isinstance(parent, list):
        i = _index(parent, last, allow_end=op.op == "add")
        if op.op == "add":
            parent.insert(i, op.value)
        elif op.op == "replace":
            parent[i] = op.value
        else:
            del parent[i]
    else:
        raise PatchError(f"path {op.path!r} goes through a value that is not a container")


def cited_urls(brief: EditableBrief) -> set[str]:
    urls = {str(s.url) for s in brief.opportunity.signals}
    urls |= {str(f.source_url) for f in brief.analysis.figures() if f.source_url is not None}
    urls |= {str(c.url) for c in brief.analysis.competitors if c.url is not None}
    return urls


def apply_patch(brief: EditableBrief, ops: list[PatchOperation]) -> EditableBrief:
    """Applies all operations atomically; raises PatchError with a reason on any failure."""
    if not ops:
        raise PatchError("the patch is empty")
    doc = copy.deepcopy(brief.model_dump(mode="json"))
    for op in ops:
        _apply_one(doc, op)
    try:
        patched = EditableBrief.model_validate(doc)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'/'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise PatchError(f"the patched brief is invalid: {problems}") from exc
    new_urls = cited_urls(patched) - cited_urls(brief)
    if new_urls:
        raise PatchError(
            f"the patch cites URLs the idea does not already cite: {sorted(new_urls)}. "
            "Use an existing source, or give an explicit assumption instead."
        )
    if patched == brief:
        raise PatchError("the patch changes nothing")
    return patched
