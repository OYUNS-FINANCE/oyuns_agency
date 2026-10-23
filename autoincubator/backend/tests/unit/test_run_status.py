"""The run status state machine."""

import pytest

from app.db.enums import TERMINAL_STATUSES, RunStatus
from app.services.runs import FINISHED, TRANSITIONS, allowed_from


def test_every_status_has_an_entry() -> None:
    assert set(TRANSITIONS) == set(RunStatus)


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_terminal_statuses_have_no_way_out(status: RunStatus) -> None:
    assert TRANSITIONS[status] == frozenset()


def test_lifecycle_paths() -> None:
    assert allowed_from(RunStatus.RUNNING) == [RunStatus.QUEUED, RunStatus.AWAITING_HUMAN]
    assert allowed_from(RunStatus.AWAITING_HUMAN) == [RunStatus.RUNNING]
    assert allowed_from(RunStatus.BUDGET_EXHAUSTED) == [RunStatus.RUNNING]
    assert set(allowed_from(RunStatus.FAILED)) == {
        RunStatus.QUEUED,
        RunStatus.RUNNING,
        RunStatus.AWAITING_HUMAN,
    }
    assert allowed_from(RunStatus.QUEUED) == []


def test_finished_statuses_include_the_pause_but_not_active_ones() -> None:
    assert TERMINAL_STATUSES < FINISHED
    assert RunStatus.AWAITING_HUMAN in FINISHED
    assert not {RunStatus.QUEUED, RunStatus.RUNNING} & FINISHED
