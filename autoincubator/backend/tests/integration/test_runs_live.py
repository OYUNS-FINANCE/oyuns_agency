"""Phase-2 acceptance: runs over HTTP, executed by a real worker, streamed over SSE.

Needs `docker compose up -d` and `alembic upgrade head`. Each test starts its own worker
(and kills it in one test); the API process is shared.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.integration.live import (
    Proc,
    SSEEvent,
    after_n,
    base_env,
    is_status,
    read_stream,
    start_api,
    start_worker,
)

pytestmark = pytest.mark.integration

SEED = {"mode": "seeded", "seed": "independent dental clinics"}


@pytest.fixture(scope="module")
def queue() -> str:
    return f"arq:test:{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def log_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("live")


@pytest.fixture(scope="module")
def api(queue: str, log_dir: Path) -> Iterator[str]:
    proc, url = start_api(base_env(queue), log_dir)
    try:
        yield url
    finally:
        proc.stop()


@pytest.fixture
def client(api: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=api, timeout=10) as c:
        yield c


def _worker(queue: str, log_dir: Path, latency_ms: int) -> Proc:
    return start_worker(base_env(queue, FAKE_LLM_LATENCY_MS=str(latency_ms)), log_dir)


def _create(client: httpx.Client, body: dict[str, Any] = SEED) -> tuple[str, float]:
    started = time.perf_counter()
    response = client.post("/api/incubator/runs", json=body)
    elapsed = time.perf_counter() - started
    assert response.status_code == 202, response.text
    return response.json()["run_id"], elapsed


def _stream_url(run_id: str) -> str:
    return f"/api/incubator/runs/{run_id}/stream"


def _ids(events: list[SSEEvent]) -> list[int]:
    return [e.id for e in events]


def _full_replay(client: httpx.Client, run_id: str, until: str = "awaiting_human") -> list[int]:
    return _ids(read_stream(client, _stream_url(run_id), stop=is_status(until)).events)


def test_start_run_streams_events_in_order_and_reaches_awaiting_human(
    client: httpx.Client, queue: str, log_dir: Path
) -> None:
    worker = _worker(queue, log_dir, latency_ms=20)
    try:
        _create(client)  # warm-up: first request pays for connection setup
        timings = [_create(client) for _ in range(5)]
        run_id = timings[-1][0]
        slowest = max(t for _, t in timings)
        assert slowest < 0.2, f"POST /runs took {slowest * 1000:.0f} ms"

        live = read_stream(client, _stream_url(run_id), stop=is_status("awaiting_human"))
    finally:
        worker.stop()

    events = live.events
    ids = _ids(events)
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert live.retry_ms == 3000
    types = [e.type for e in events]
    statuses = [e.data["data"]["status"] for e in events if e.type == "run.status"]
    assert statuses == ["queued", "running", "awaiting_human"]
    assert types[0] == "run.status" and types[-1] == "run.status"
    assert types.index("agent.started") < types.index("agent.tool_call")
    assert [e.data["data"]["node"] for e in events if e.type == "agent.started"] == [
        "scout",
        "analyst",
        "skeptic",
    ]
    assert types[-2] == "run.interrupted"
    created = [e.data["data"] for e in events if e.type == "idea.created"]
    interrupted = events[-2].data["data"]
    assert [c["idea_id"] for c in created] == interrupted["idea_ids"]
    assert all(e.data["run_id"] == run_id for e in events)

    # A fresh replay from the start yields exactly the same events.
    assert _full_replay(client, run_id) == ids

    detail = client.get(f"/api/incubator/runs/{run_id}").json()
    assert detail["status"] == "awaiting_human"
    assert detail["finished_at"] is not None and detail["error"] is None
    assert detail["viable_count"] == interrupted["viable_count"]
    ideas = detail["ideas"]
    assert [i["id"] for i in ideas] == [c["idea_id"] for c in created]
    assert [i["rank"] for i in ideas] == list(range(1, len(ideas) + 1))
    assert 3 <= len(ideas) <= 5
    for idea in ideas:
        assert idea["version"] == 1 and idea["version_source"] == "agent"
        assert idea["status"] == "active"
        assert idea["title"] == idea["opportunity"]["title"]
        assert idea["opportunity"]["id"] == idea["key"]
        assert len(idea["critique"]["scores"]) == 7
    assert detail["budget"]["tokens_used"] > 0 and detail["budget"]["searches_used"] > 0

    listed = client.get("/api/incubator/runs", params={"limit": 100}).json()
    assert run_id in {r["id"] for r in listed["items"]}


def test_reconnect_with_last_event_id_loses_and_duplicates_nothing(
    client: httpx.Client, queue: str, log_dir: Path
) -> None:
    worker = _worker(queue, log_dir, latency_ms=100)
    try:
        run_id, _ = _create(client)
        first = read_stream(client, _stream_url(run_id), stop=after_n(10))
        assert not first.closed_by_server
        detail = client.get(f"/api/incubator/runs/{run_id}").json()
        assert detail["status"] == "running", "disconnect must happen mid-run"
        time.sleep(0.5)  # events keep being produced while we are away
        second = read_stream(
            client,
            _stream_url(run_id),
            last_event_id=first.events[-1].id,
            stop=is_status("awaiting_human"),
        )
    finally:
        worker.stop()

    combined = _ids(first.events) + _ids(second.events)
    assert len(first.events) == 10
    assert second.events[0].id > first.events[-1].id
    assert len(set(combined)) == len(combined), "duplicates after reconnect"
    assert combined == _full_replay(client, run_id), "events lost across reconnect"


def test_killed_worker_is_recovered_and_resumes_from_the_checkpoint(
    client: httpx.Client, queue: str, log_dir: Path
) -> None:
    first = _worker(queue, log_dir, latency_ms=300)
    second: Proc | None = None
    try:
        run_id, _ = _create(client)
        before = read_stream(
            client,
            _stream_url(run_id),
            stop=lambda e: e.type == "agent.tool_call" and e.agent == "analyst",
        )
        first.kill()
        assert client.get(f"/api/incubator/runs/{run_id}").json()["status"] == "running"

        time.sleep(2.5)  # > RUN_LEASE_TTL_S: the dead worker's lease has expired
        second = _worker(queue, log_dir, latency_ms=0)
        after = read_stream(
            client,
            _stream_url(run_id),
            last_event_id=before.events[-1].id,
            stop=is_status("awaiting_human", "failed"),
        )
    finally:
        first.kill()
        if second is not None:
            second.stop()

    events = before.events + after.events
    recovered = [
        e.data["data"]
        for e in after.events
        if e.type == "run.status" and e.data["data"]["previous"] == "running"
    ]
    assert len(recovered) == 2  # the recovery notice, then running → awaiting_human
    assert recovered[0]["status"] == "running" and "Recovered" in recovered[0]["detail"]
    # The Scout step was checkpointed before the kill, so it never ran again.
    started = [e.data["data"]["node"] for e in events if e.type == "agent.started"]
    assert started.count("scout") == 1
    assert started.count("analyst") == 2  # interrupted step re-run from its checkpoint
    assert events[-1].data["data"]["status"] == "awaiting_human"
    detail = client.get(f"/api/incubator/runs/{run_id}").json()
    assert detail["status"] == "awaiting_human" and 3 <= len(detail["ideas"]) <= 5
    assert "run.recovery_enqueued" in second.log()


def test_budget_exhaustion_stops_the_run_with_a_clear_status(
    client: httpx.Client, queue: str, log_dir: Path
) -> None:
    worker = _worker(queue, log_dir, latency_ms=0)
    try:
        run_id, _ = _create(client, {**SEED, "budget": {"max_tokens": 6000}})
        result = read_stream(client, _stream_url(run_id), timeout_s=60)
    finally:
        worker.stop()

    assert result.closed_by_server, "stream must close on a terminal status"
    types = [e.type for e in result.events]
    warning = result.events[types.index("budget.warning")].data["data"]
    exhausted = result.events[types.index("budget.exhausted")].data["data"]
    assert types.index("budget.warning") < types.index("budget.exhausted")
    assert warning["kind"] == exhausted["kind"] == "tokens"
    assert warning["used"] >= 0.8 * 6000 and exhausted["used"] >= 6000
    error = result.events[types.index("run.error")].data["data"]
    assert error["code"] == "budget_exhausted"
    final = result.events[-1].data["data"]
    assert final == {
        "status": "budget_exhausted",
        "previous": "running",
        "detail": error["message"],
    }

    detail = client.get(f"/api/incubator/runs/{run_id}").json()
    assert detail["status"] == "budget_exhausted"
    assert detail["error"]["code"] == "budget_exhausted"
    assert detail["budget"]["max_tokens"] == 6000
    assert detail["budget"]["tokens_used"] >= 6000
    assert detail["ideas"] == []


def test_profile_round_trip_and_mode_b_snapshot(
    client: httpx.Client, queue: str, log_dir: Path
) -> None:
    profile = {
        "skills": ["python", "sales"],
        "region": "EU",
        "capital_usd": 20000,
        "risk_tolerance": "low",
        "weekly_hours": 30,
        "rejected_idea_reasons": ["too regulated"],
    }
    put = client.put("/api/incubator/profile", json=profile)
    assert put.status_code == 200, put.text
    got = client.get("/api/incubator/profile").json()
    assert got["profile"] == profile and got["updated_at"] is not None

    worker = _worker(queue, log_dir, latency_ms=0)
    try:
        run_id, _ = _create(client, {"mode": "autonomous"})
        read_stream(client, _stream_url(run_id), stop=is_status("awaiting_human", "failed"))
    finally:
        worker.stop()
    detail = client.get(f"/api/incubator/runs/{run_id}").json()
    assert detail["input"]["founder_profile"] == profile
    assert detail["mode"] == "autonomous" and detail["seed"] is None
    assert detail["status"] == "awaiting_human"


def test_unknown_run_is_a_json_404(client: httpx.Client) -> None:
    for path in ("", "/stream"):
        r = client.get(f"/api/incubator/runs/{uuid.uuid4()}{path}")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"
