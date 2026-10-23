"""Phase-4 acceptance over HTTP: co-working on a paused run, with a real API and worker."""

from __future__ import annotations

import concurrent.futures
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.integration.live import (
    Proc,
    SSEEvent,
    base_env,
    is_status,
    read_chat,
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
    return tmp_path_factory.mktemp("cowork")


@pytest.fixture(scope="module")
def api(queue: str, log_dir: Path) -> Iterator[str]:
    proc, url = start_api(base_env(queue), log_dir)
    try:
        yield url
    finally:
        proc.stop()


@pytest.fixture(scope="module")
def worker(queue: str, log_dir: Path) -> Iterator[Proc]:
    proc = start_worker(base_env(queue, FAKE_LLM_LATENCY_MS="30"), log_dir)
    try:
        yield proc
    finally:
        proc.stop()


@pytest.fixture
def client(api: str, worker: Proc) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=api, timeout=10) as c:
        yield c


def _runs(run_id: str) -> str:
    return f"/api/incubator/runs/{run_id}"


def _paused_run(client: httpx.Client) -> tuple[str, list[dict[str, Any]], int]:
    """A run at the checkpoint: (run id, its ideas, last event id)."""
    response = client.post("/api/incubator/runs", json=SEED)
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    events = read_stream(client, f"{_runs(run_id)}/stream", stop=is_status("awaiting_human"))
    detail = client.get(_runs(run_id)).json()
    assert detail["status"] == "awaiting_human"
    return run_id, detail["ideas"], events.events[-1].id


def _wait_for(client: httpx.Client, run_id: str, after: int, pred: Any) -> list[SSEEvent]:
    return read_stream(client, f"{_runs(run_id)}/stream", last_event_id=after, stop=pred).events


def test_chat_apply_patch_then_rescore_updates_the_card(client: httpx.Client) -> None:
    run_id, ideas, cursor = _paused_run(client)
    idea = ideas[0]
    base = f"{_runs(run_id)}/ideas/{idea['id']}"

    events = read_chat(
        client, f"{base}/cowork", {"agent": "analyst", "content": "Focus on EU chains"}
    )
    names = [e.event for e in events]
    assert names[0] == "started" and names[-1] == "completed"
    assert names.count("delta") > 1, "the reply must arrive in pieces"
    reply = events[-1].data
    assert "".join(e.data["text"] for e in events if e.event == "delta") == reply["content"]
    assert reply["state"] == "complete" and reply["proposed_patch"]
    assert events[0].data["assistant_message"]["id"] == reply["id"]

    # Version 2 from the proposal; applying it again is idempotent.
    applied = client.post(f"{base}/versions", json={"message_id": reply["id"]})
    assert applied.status_code == 201, applied.text
    again = client.post(f"{base}/versions", json={"message_id": reply["id"]})
    assert again.status_code == 200 and again.json()["version"] == 2
    detail = client.get(base).json()
    assert [(v["version"], v["source"]) for v in detail["versions"]] == [
        (1, "agent"),
        (2, "cowork"),
    ]
    v1, v2 = detail["versions"]
    assert v2["patch"] == reply["proposed_patch"] and v2["message_id"] == reply["id"]
    assert v1["opportunity"]["one_liner"] != v2["opportunity"]["one_liner"]
    assert detail["idea"]["score_stale"] is True
    messages = client.get(f"{base}/cowork").json()["items"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["applied_version"] == 2

    # Re-score in the worker, streamed: the card gets a fresh score at version 3.
    accepted = client.post(f"{base}/rescore")
    assert accepted.status_code == 202, accepted.text
    streamed = _wait_for(
        client,
        run_id,
        cursor,
        lambda e: e.type == "agent.completed" and e.data["data"]["node"] == "rescore",
    )
    started = [e for e in streamed if e.type == "agent.started"]
    assert started[-1].data["data"] == {
        "node": "rescore",
        "iteration": None,
        "items": 1,
        "idea_id": idea["id"],
    }
    updates = [e.data["data"] for e in streamed if e.type == "idea.updated"]
    assert [u["source"] for u in updates] == ["cowork", "rescore"]
    card = next(i for i in client.get(_runs(run_id)).json()["ideas"] if i["id"] == idea["id"])
    assert card["version"] == 3 and card["version_source"] == "rescore"
    assert card["score_stale"] is False
    assert card["composite_score"] == updates[-1]["composite_score"]
    assert card["opportunity"]["one_liner"] == v2["opportunity"]["one_liner"]


def test_merge_creates_a_new_scored_idea_streamed_live(client: httpx.Client) -> None:
    run_id, ideas, cursor = _paused_run(client)
    sources = [ideas[0]["id"], ideas[1]["id"]]
    accepted = client.post(f"{_runs(run_id)}/ideas/merge", json={"idea_ids": sources})
    assert accepted.status_code == 202, accepted.text

    streamed = _wait_for(
        client,
        run_id,
        cursor,
        lambda e: e.type == "agent.completed" and e.data["data"]["node"] == "merge",
    )
    types = [(e.type, e.agent) for e in streamed]
    assert types[0] == ("agent.started", "scout")
    assert ("agent.tool_call", "analyst") in types, "the Analyst searched for the hybrid"
    created = [e.data["data"] for e in streamed if e.type == "idea.created"]
    assert len(created) == 1 and created[0]["key"] == "mrg-01"
    assert streamed[-1].data["data"]["summary"] == {"created": 1, "failed": 0}
    assert streamed[-1].data["data"]["idea_id"] == created[0]["idea_id"]

    detail = client.get(_runs(run_id)).json()
    hybrid = next(i for i in detail["ideas"] if i["id"] == created[0]["idea_id"])
    assert hybrid["version_source"] == "merge" and hybrid["merged_from"] == sources
    assert hybrid["title"].startswith("Hybrid:")
    assert len(hybrid["critique"]["scores"]) == 7 and hybrid["composite_score"] is not None
    assert hybrid["analysis"]["opportunity_id"] == "mrg-01"
    assert sorted(i["rank"] for i in detail["ideas"]) == list(range(1, len(ideas) + 2))
    assert all(i["status"] == "active" for i in detail["ideas"])  # sources stay selectable


def test_select_clicked_twice_resumes_once_and_completes(client: httpx.Client) -> None:
    run_id, ideas, cursor = _paused_run(client)
    chosen = ideas[1]["id"]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        responses = list(
            pool.map(
                lambda _: client.post(f"{_runs(run_id)}/select", json={"idea_id": chosen}),
                range(4),
            )
        )
    assert [r.status_code for r in responses] == [202] * 4
    assert {r.json()["selected_idea_id"] for r in responses} == {chosen}

    rest = read_stream(client, f"{_runs(run_id)}/stream", last_event_id=cursor).events
    types = [e.type for e in rest]
    assert types.count("run.resumed") == 1 and types.count("run.completed") == 1
    assert rest[-1].data["data"]["status"] == "completed"
    assert client.get(_runs(run_id)).json()["selected_idea_id"] == chosen

    other = client.post(f"{_runs(run_id)}/select", json={"idea_id": ideas[0]["id"]})
    assert other.status_code == 409 and other.json()["error"]["code"] == "run_not_paused"


def test_cowork_calls_return_409_unless_the_run_is_paused(
    client: httpx.Client, queue: str, log_dir: Path
) -> None:
    done, ideas, _ = _paused_run(client)
    idea = ideas[0]["id"]
    client.post(f"{_runs(done)}/select", json={"idea_id": idea})
    read_stream(client, f"{_runs(done)}/stream", stop=is_status("completed"))

    # A run still queued: no worker consumes this queue.
    queued_api, url = start_api(base_env(f"{queue}:idle"), log_dir)
    try:
        with httpx.Client(base_url=url, timeout=10) as idle:
            queued = idle.post("/api/incubator/runs", json=SEED).json()["run_id"]
            for run_id, c in ((done, client), (queued, idle)):
                base = _runs(run_id)
                target = f"{base}/ideas/{idea}"
                calls = [
                    c.post(f"{target}/cowork", json={"agent": "scout", "content": "hi"}),
                    c.post(f"{target}/versions", json={"message_id": str(uuid.uuid4())}),
                    c.post(f"{target}/rescore"),
                    c.post(f"{target}/reject", json={"reason": "x"}),
                    c.post(f"{base}/ideas/merge", json={"idea_ids": [idea, str(uuid.uuid4())]}),
                    c.post(f"{base}/select", json={"idea_id": str(uuid.uuid4())}),
                ]
                assert [r.status_code for r in calls] == [409] * 6, [r.text for r in calls]
                assert {r.json()["error"]["code"] for r in calls} == {"run_not_paused"}
    finally:
        queued_api.stop()
