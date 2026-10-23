"""JSON Patch against an idea brief: RFC 6902 subset plus the brief's sourcing rules."""

from typing import Any

import pytest

from app.services.brief_patch import PatchError, PatchOperation, apply_patch
from tests import factories as f


def _ops(*ops: dict[str, Any]) -> list[PatchOperation]:
    return [PatchOperation.model_validate(o) for o in ops]


def test_replace_and_add_produce_a_valid_new_brief() -> None:
    brief = f.editable_brief()
    patched = apply_patch(
        brief,
        _ops(
            {
                "op": "replace",
                "path": "/opportunity/target_customer",
                "value": "Multi-chair EU clinics",
            },
            {
                "op": "add",
                "path": "/analysis/segments/-",
                "value": {"name": "Chains", "description": "Groups of 5+ clinics."},
            },
        ),
    )
    assert patched.opportunity.target_customer == "Multi-chair EU clinics"
    assert [s.name for s in patched.analysis.segments] == ["Independents", "Chains"]
    assert brief.opportunity.target_customer != patched.opportunity.target_customer  # immutable


@pytest.mark.parametrize(
    ("op", "reason"),
    [
        ({"op": "replace", "path": "/critique/scores/0/score", "value": 10}, "re-score"),
        ({"op": "replace", "path": "/opportunity/id", "value": "opp-99"}, "read-only"),
        ({"op": "replace", "path": "/analysis/opportunity_id", "value": "x"}, "read-only"),
        ({"op": "replace", "path": "opportunity/title", "value": "x"}, "must start"),
        ({"op": "replace", "path": "/opportunity/nope", "value": "x"}, "does not exist"),
        ({"op": "remove", "path": "/analysis/segments/5"}, "out of range"),
        ({"op": "remove", "path": "/opportunity/problem"}, "invalid"),
        ({"op": "replace", "path": "/opportunity/business_model", "value": "b2g"}, "invalid"),
    ],
)
def test_forbidden_or_broken_operations_are_refused(op: dict[str, Any], reason: str) -> None:
    with pytest.raises(PatchError, match=reason):
        apply_patch(f.editable_brief(), _ops(op))


def test_a_figure_without_source_or_assumption_is_refused() -> None:
    with pytest.raises(PatchError, match="source_url or an explicit assumption"):
        apply_patch(
            f.editable_brief(),
            _ops(
                {
                    "op": "replace",
                    "path": "/analysis/sizing/sam",
                    "value": {"value": 1, "unit": "USD"},
                }
            ),
        )


def test_sizing_must_stay_nested() -> None:
    with pytest.raises(PatchError, match="SOM <= SAM <= TAM"):
        apply_patch(
            f.editable_brief(),
            _ops({"op": "replace", "path": "/analysis/sizing/som/value", "value": 9e9}),
        )


def test_only_urls_the_idea_already_cites_are_allowed() -> None:
    brief = f.editable_brief()
    reuse = {"op": "replace", "path": "/analysis/competitors/0/url", "value": f.DENTAL_URL}
    assert str(apply_patch(brief, _ops(reuse)).analysis.competitors[0].url) == f.DENTAL_URL
    new = {"op": "replace", "path": "/analysis/competitors/0/url", "value": f.HVAC_URL}
    with pytest.raises(PatchError, match="does not already cite"):
        apply_patch(brief, _ops(new))


def test_empty_and_no_op_patches_are_refused() -> None:
    brief = f.editable_brief()
    with pytest.raises(PatchError, match="empty"):
        apply_patch(brief, [])
    same = {"op": "replace", "path": "/opportunity/title", "value": brief.opportunity.title}
    with pytest.raises(PatchError, match="changes nothing"):
        apply_patch(brief, _ops(same))


def test_operations_apply_atomically() -> None:
    brief = f.editable_brief()
    ok = {"op": "replace", "path": "/opportunity/title", "value": "New title"}
    bad = {"op": "remove", "path": "/opportunity/missing"}
    with pytest.raises(PatchError):
        apply_patch(brief, _ops(ok, bad))
    assert brief.opportunity.title == "Dental reminders"
