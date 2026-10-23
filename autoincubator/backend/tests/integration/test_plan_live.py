"""Phase-5 acceptance over HTTP: select → Phase 2 → completed run with a plan, exported."""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.agents.editor.schemas import BusinessPlan
from app.services.export.markdown import undisclosed_untraced
from tests.integration.live import Proc, base_env, is_status, read_stream, start_api, start_worker

pytestmark = pytest.mark.integration

SEED = {"mode": "seeded", "seed": "independent dental clinics"}
PHASE2 = ["product_architect", "gtm_strategist", "financial_modeler", "editor"]


def _pango_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except OSError:
        return False
    return True


@pytest.fixture(scope="module")
def queue() -> str:
    return f"arq:test:{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def log_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("plan")


@pytest.fixture(scope="module")
def api(queue: str, log_dir: Path) -> Iterator[str]:
    proc, url = start_api(base_env(queue), log_dir)
    try:
        yield url
    finally:
        proc.stop()


@pytest.fixture(scope="module")
def worker(queue: str, log_dir: Path) -> Iterator[Proc]:
    proc = start_worker(base_env(queue, FAKE_LLM_LATENCY_MS="20"), log_dir)
    try:
        yield proc
    finally:
        proc.stop()


@pytest.fixture
def client(api: str, worker: Proc) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=api, timeout=30) as c:
        yield c


def _runs(run_id: str) -> str:
    return f"/api/incubator/runs/{run_id}"


def test_full_run_with_fakes_completes_with_a_traceable_exported_plan(
    client: httpx.Client,
) -> None:
    run_id = client.post("/api/incubator/runs", json=SEED).json()["run_id"]
    paused = read_stream(client, f"{_runs(run_id)}/stream", stop=is_status("awaiting_human"))
    idea = client.get(_runs(run_id)).json()["ideas"][0]

    # No plan while paused.
    missing = client.get(f"{_runs(run_id)}/plan")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "plan_not_found"
    assert client.get(f"{_runs(run_id)}/plan/export").status_code == 404

    assert client.post(f"{_runs(run_id)}/select", json={"idea_id": idea["id"]}).status_code == 202
    done = read_stream(
        client, f"{_runs(run_id)}/stream", last_event_id=paused.events[-1].id, timeout_s=90
    )
    assert done.closed_by_server
    started = [e.data["data"]["node"] for e in done.events if e.type == "agent.started"]
    trail = [
        (e.type, e.data["data"].get("node") or e.data["data"].get("status")) for e in done.events
    ]
    assert sorted(started) == sorted(PHASE2), trail
    assert started[-1] == "editor"  # the fan-in runs after the three parallel agents
    (completed,) = [e for e in done.events if e.type == "run.completed"]
    assert completed.data["data"]["plan_version"] == 1
    assert client.get(_runs(run_id)).json()["status"] == "completed"

    body = client.get(f"{_runs(run_id)}/plan").json()
    plan = BusinessPlan.model_validate(body["plan"])
    assert body["version"] == 1
    assert plan.idea_id == idea["id"]
    assert plan.brief.opportunity.title == idea["title"]
    assert set(plan.financials.scenarios) == {"base", "bear", "bull"}
    assert [c.code for c in plan.contradictions] == []
    assert {f["key"] for f in body["engine_formulas"]} >= {"ltv", "months.cash"}

    md = client.get(f"{_runs(run_id)}/plan/export", params={"format": "md"})
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/markdown")
    assert md.headers["content-disposition"].startswith("attachment; filename=")
    assert md.headers["content-disposition"].endswith('-v1.md"')
    assert "## Appendix: Sources & Assumptions" in md.text
    assert undisclosed_untraced(plan, md.text) == []

    bad = client.get(f"{_runs(run_id)}/plan/export", params={"format": "docx"})
    assert bad.status_code == 422

    if sys.platform == "darwin" and not _pango_available():
        pytest.skip("Pango not loadable: run with DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib")
    pdf = client.get(f"{_runs(run_id)}/plan/export", params={"format": "pdf"})
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")


def test_plan_of_an_unknown_run_is_404(client: httpx.Client) -> None:
    response = client.get(f"{_runs(str(uuid.uuid4()))}/plan")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
