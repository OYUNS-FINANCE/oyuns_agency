"""Request context: a request id, `run_id` in the logs, and an HTTP span (ADR 0008).

Pure ASGI (not BaseHTTPMiddleware) so streaming responses and context variables behave.
A request whose path names a run opens its span in that run's trace; others get their own.
The SSE stream is not spanned: it stays open for the whole run.
"""

from __future__ import annotations

import re
import time
import uuid

import structlog
from opentelemetry import trace
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger
from app.core.telemetry import run_span

log = get_logger(__name__)
tracer = trace.get_tracer(__name__)

_RUN_PATH = re.compile(r"/runs/([0-9a-fA-F-]{36})(?:/|$)")
QUIET_PATHS = ("/api/health",)


def run_id_from_path(path: str) -> uuid.UUID | None:
    match = _RUN_PATH.search(path)
    if match is None:
        return None
    try:
        return uuid.UUID(match.group(1))
    except ValueError:
        return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        method: str = scope["method"]
        run_id = run_id_from_path(path)
        request_id = uuid.uuid4().hex[:12]
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            if path.startswith(QUIET_PATHS) or path.endswith("/stream"):
                await self._call_bound(scope, receive, send_wrapper, run_id)
                return
            started = time.monotonic()
            if run_id is not None:
                span_cm = run_span(f"HTTP {method}", run_id)
            else:
                span_cm = tracer.start_as_current_span(f"HTTP {method}")
            with span_cm as span:
                span.set_attribute("http.method", method)
                span.set_attribute("http.route_path", path)
                try:
                    await self._call_bound(scope, receive, send_wrapper, run_id)
                finally:
                    span.set_attribute("http.status_code", status_code)
                    log.info(
                        "http.request",
                        method=method,
                        path=path,
                        status=status_code,
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )

    async def _call_bound(
        self, scope: Scope, receive: Receive, send: Send, run_id: uuid.UUID | None
    ) -> None:
        if run_id is None:
            await self.app(scope, receive, send)
            return
        with structlog.contextvars.bound_contextvars(run_id=str(run_id)):
            await self.app(scope, receive, send)
