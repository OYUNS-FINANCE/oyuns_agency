"""Tracing: a run's trace id is its UUID, spans nest across API/worker/nodes/LLM/search,
and log lines carry run_id, node and trace ids."""

import io
import json
import uuid
from collections.abc import Iterator

import pytest
import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import app.core.telemetry as telemetry
from app.agents.common.schemas import RunInput
from app.api.middleware import run_id_from_path
from app.core.config import Settings
from app.core.logging import configure_logging, get_logger
from app.core.telemetry import RunIdGenerator, run_span, traced_node
from app.graph.builder import compile_graph
from app.graph.state import Phase1State
from app.providers.factory import build_deps
from tests import factories as f


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(id_generator=RunIdGenerator())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Module-level tracers were created against the default provider: point them at ours.
    for module in telemetry, __import__("app.providers.llm.base", fromlist=["x"]):
        monkeypatch.setattr(module, "tracer", provider.get_tracer("test"))
    import app.providers.search.base as search_base

    monkeypatch.setattr(search_base, "tracer", provider.get_tracer("test"))
    yield exporter
    exporter.clear()


def test_run_span_uses_the_run_uuid_as_trace_id(spans: InMemorySpanExporter) -> None:
    run_id = uuid.uuid4()
    with run_span("api.create", run_id):
        pass
    with run_span("worker.start", run_id):
        pass
    finished = spans.get_finished_spans()
    assert [s.context.trace_id for s in finished if s.context] == [run_id.int, run_id.int]
    assert all(s.parent is None for s in finished)  # two roots in one trace
    assert finished[0].attributes and finished[0].attributes["run_id"] == str(run_id)


def test_run_span_is_a_root_even_inside_another_span(spans: InMemorySpanExporter) -> None:
    run_id = uuid.uuid4()
    other = telemetry.tracer.start_as_current_span("HTTP POST")
    with other, run_span("api.enqueue", run_id):
        pass
    by_name = {s.name: s for s in spans.get_finished_spans()}
    assert by_name["api.enqueue"].context.trace_id == run_id.int
    assert by_name["api.enqueue"].parent is None
    assert by_name["HTTP POST"].context.trace_id != run_id.int


def test_path_run_id_extraction() -> None:
    rid = uuid.uuid4()
    assert run_id_from_path(f"/api/incubator/runs/{rid}") == rid
    assert run_id_from_path(f"/api/incubator/runs/{rid}/ideas/x/cowork") == rid
    assert run_id_from_path("/api/incubator/runs") is None
    assert run_id_from_path("/api/incubator/runs/not-a-uuid-not-a-uuid-not-a-uuid-xx") is None


async def test_a_graph_run_is_one_trace_of_nodes_llm_and_search_spans(
    spans: InMemorySpanExporter,
) -> None:
    run_id = uuid.uuid4()
    deps = build_deps(f.settings())  # offline responder, mock search
    graph = compile_graph(InMemorySaver())
    initial: Phase1State = {
        "run_id": str(run_id),
        "run_input": RunInput.model_validate({"mode": "seeded", "seed": "dental clinics"}),
    }
    config: RunnableConfig = {"configurable": {"thread_id": str(run_id)}}
    with run_span("worker.start_run", run_id):
        await graph.ainvoke(initial, config, context=deps)
    finished = spans.get_finished_spans()
    assert {s.context.trace_id for s in finished if s.context} == {run_id.int}
    names = {s.name for s in finished}
    assert {"node.scout", "node.analyst", "node.skeptic", "node.rank"} <= names
    assert {"llm.call", "search"} <= names
    by_id = {s.context.span_id: s for s in finished if s.context}
    llm = next(s for s in finished if s.name == "llm.call")
    chain = []
    cursor = llm
    while cursor.parent is not None:
        cursor = by_id[cursor.parent.span_id]
        chain.append(cursor.name)
    assert chain[0].startswith("node.") and chain[-1] == "worker.start_run"
    assert llm.attributes and llm.attributes["llm.agent"] and "llm.cost_usd" in llm.attributes


async def test_traced_node_records_errors_and_binds_log_context(
    spans: InMemorySpanExporter,
) -> None:
    async def boom(state: dict[str, str], runtime: object) -> dict[str, str]:
        raise RuntimeError("kaboom")

    wrapped = traced_node("scout", boom)
    with pytest.raises(RuntimeError):
        await wrapped({"run_id": "r1"}, object())
    (span,) = spans.get_finished_spans()
    assert span.name == "node.scout" and span.status.status_code == trace.StatusCode.ERROR


def test_log_lines_carry_run_id_node_and_trace_ids(spans: InMemorySpanExporter) -> None:
    stream = io.StringIO()
    configure_logging("INFO", stream=stream, service="worker")
    run_id = uuid.uuid4()
    with (
        run_span("worker.start_run", run_id),
        structlog.contextvars.bound_contextvars(node="scout"),
    ):
        get_logger("t").info("hello")
    line = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert line["run_id"] == str(run_id) and line["node"] == "scout"
    assert line["service"] == "worker"
    assert line["trace_id"] == f"{run_id.int:032x}" and len(line["span_id"]) == 16


def test_tracing_is_off_without_an_endpoint() -> None:
    assert telemetry.setup_tracing(Settings(_env_file=None), "api") is False
