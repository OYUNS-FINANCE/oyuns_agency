"""Tracing and log context (ADR 0008).

Tracing is OpenTelemetry, exported over OTLP/HTTP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set
and a no-op otherwise. **A run's trace id is the run's UUID.** Every process that works on a
run (the API request that created it, the worker job that executes it, the resume job after
the founder selects, co-working chat) opens its root span under that trace id, so one trace
shows the whole run across API → worker → graph nodes → LLM and search calls, even across
the pause at the checkpoint and across a worker restart, with no context to pass through
Redis. Look a run up in the tracing UI by pasting its id.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import random
import uuid
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, cast

import sentry_sdk
import structlog
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.id_generator import IdGenerator
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from app.core.config import Settings

tracer = trace.get_tracer("autoincubator")

_forced_trace_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "forced_trace_id", default=None
)
_configured = False


class RunIdGenerator(IdGenerator):
    """Random ids, except that a root span opened by `run_span` takes the run's UUID."""

    def generate_span_id(self) -> int:
        return random.getrandbits(64) or 1

    def generate_trace_id(self) -> int:
        return _forced_trace_id.get() or random.getrandbits(128) or 1


def setup_tracing(
    settings: Settings, service: str, *, exporter: SpanExporter | None = None
) -> bool:
    """Installs the tracer provider once per process. Returns whether tracing is on.
    `exporter` is for tests; production uses OTLP/HTTP from the settings."""
    global _configured
    if _configured:
        return True
    endpoint = settings.otel_exporter_otlp_endpoint
    if exporter is None and not endpoint:
        return False
    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        assert endpoint is not None
        exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")
    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: f"{settings.otel_service_name}-{service}"}),
        id_generator=RunIdGenerator(),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True
    return True


def shutdown_tracing() -> None:
    global _configured
    provider = trace.get_tracer_provider()
    if _configured and isinstance(provider, TracerProvider):
        provider.shutdown()
    _configured = False


@contextlib.contextmanager
def run_span(
    name: str, run_id: uuid.UUID | str, *, kind: SpanKind = SpanKind.INTERNAL, **attributes: Any
) -> Iterator[Span]:
    """A root span in the run's trace, with `run_id` bound into every log line inside."""
    rid = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
    token = _forced_trace_id.set(rid.int)
    try:
        # An empty context makes this a root span even inside another span (e.g. an HTTP one).
        span = tracer.start_span(
            name, context=Context(), kind=kind, attributes={"run_id": str(rid), **attributes}
        )
    finally:
        _forced_trace_id.reset(token)
    with (
        structlog.contextvars.bound_contextvars(run_id=str(rid)),
        trace.use_span(span, end_on_exit=True),
    ):
        yield span


def traced_node[F: Callable[..., Awaitable[Any]]](name: str, fn: F) -> F:
    """Wraps a graph node `(state, runtime)`: a span named `node.<name>` and `node`/`run_id`
    in the logs. `functools.wraps` keeps the signature LangGraph inspects for `runtime`."""

    @functools.wraps(fn)
    async def wrapper(state: Any, runtime: Any) -> Any:
        run_id = state.get("run_id") if isinstance(state, dict) else None
        bound: dict[str, Any] = {"node": name}
        if run_id:
            bound["run_id"] = str(run_id)
        with (
            structlog.contextvars.bound_contextvars(**bound),
            tracer.start_as_current_span(f"node.{name}", attributes={"node": name}) as span,
        ):
            try:
                return await fn(state, runtime)
            except BaseException as exc:
                span.set_status(Status(StatusCode.ERROR, f"{type(exc).__name__}: {exc}"[:200]))
                raise

    return cast(F, wrapper)


def current_ids() -> dict[str, str]:
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return {}
    return {"trace_id": f"{ctx.trace_id:032x}", "span_id": f"{ctx.span_id:016x}"}


def setup_sentry(settings: Settings, service: str) -> bool:
    """Reports unhandled exceptions and ERROR logs to Sentry. Off unless SENTRY_DSN is set."""
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        send_default_pii=False,
        traces_sample_rate=0.0,  # traces go through OpenTelemetry
        server_name=service,
    )
    sentry_sdk.set_tag("service", service)
    return True
