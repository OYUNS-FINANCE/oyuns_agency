"""Real API and worker processes for integration tests, plus a minimal SSE reader.

httpx's ASGI transport buffers whole responses, so streaming is tested against a real
uvicorn. Each test session uses its own arq queue so a developer's worker is never involved.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

BACKEND = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def base_env(queue: str, **overrides: str) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(BACKEND),
        "LLM_PROVIDER": "fake",
        "SEARCH_PROVIDER": "mock",
        "LANGGRAPH_STRICT_MSGPACK": "true",
        "ARQ_QUEUE_NAME": queue,
        "RUN_LEASE_TTL_S": "2",
        "SSE_POLL_INTERVAL_S": "1",
        "LOG_LEVEL": "INFO",
        # Tests create far more runs than a person would; the limiter has its own tests.
        "RATE_LIMIT_ENABLED": "false",
        "DAILY_COST_CAP_USD": "0",
        **overrides,
    }


@dataclass
class Proc:
    name: str
    popen: subprocess.Popen[bytes]
    log_path: Path

    def kill(self) -> None:
        """SIGKILL: no shutdown hooks, no lease release, like a crashed machine."""
        if self.popen.poll() is None:
            self.popen.send_signal(signal.SIGKILL)
            self.popen.wait(timeout=10)

    def stop(self) -> None:
        if self.popen.poll() is None:
            self.popen.terminate()
            try:
                self.popen.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.kill()

    def log(self) -> str:
        return self.log_path.read_text(errors="replace")


def spawn(name: str, args: list[str], env: Mapping[str, str], log_dir: Path) -> Proc:
    log_path = log_dir / f"{name}-{time.monotonic_ns()}.log"
    handle = log_path.open("wb")
    popen = subprocess.Popen(
        [sys.executable, *args], cwd=BACKEND, env=dict(env), stdout=handle, stderr=handle
    )
    return Proc(name, popen, log_path)


def start_api(env: Mapping[str, str], log_dir: Path) -> tuple[Proc, str]:
    port = free_port()
    proc = spawn("api", ["-m", "uvicorn", "app.main:app", "--port", str(port)], env, log_dir)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.popen.poll() is not None:
            raise RuntimeError(f"API exited early:\n{proc.log()}")
        try:
            if httpx.get(f"{url}/api/health", timeout=1).status_code == 200:
                return proc, url
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    proc.stop()
    raise RuntimeError(f"API did not become healthy:\n{proc.log()}")


def start_worker(env: Mapping[str, str], log_dir: Path) -> Proc:
    proc = spawn("worker", ["-m", "arq", "app.worker.main.WorkerSettings"], env, log_dir)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.popen.poll() is not None:
            raise RuntimeError(f"worker exited early:\n{proc.log()}")
        if "worker.startup" in proc.log():
            return proc
        time.sleep(0.1)
    proc.stop()
    raise RuntimeError(f"worker did not start:\n{proc.log()}")


@dataclass
class SSEEvent:
    id: int
    data: dict[str, Any]

    @property
    def type(self) -> str:
        return str(self.data["type"])

    @property
    def agent(self) -> str | None:
        agent = self.data.get("agent")
        return None if agent is None else str(agent)


@dataclass
class StreamResult:
    events: list[SSEEvent] = field(default_factory=list)
    closed_by_server: bool = False
    retry_ms: int | None = None


def read_stream(
    client: httpx.Client,
    url: str,
    *,
    last_event_id: int | None = None,
    stop: Callable[[SSEEvent], bool] | None = None,
    timeout_s: float = 60,
) -> StreamResult:
    """Reads events until `stop(event)` is true (then disconnects) or the server closes."""
    headers = {"Accept": "text/event-stream"}
    if last_event_id is not None:
        headers["Last-Event-ID"] = str(last_event_id)
    result = StreamResult()
    deadline = time.monotonic() + timeout_s
    fields: dict[str, str] = {}
    with client.stream("GET", url, headers=headers, timeout=timeout_s) as response:
        response.raise_for_status()
        assert response.headers["content-type"].startswith("text/event-stream")
        # Proxies (the Next dev server included) must not gzip, and so buffer, the stream.
        assert "no-transform" in response.headers["cache-control"]
        for line in response.iter_lines():
            if time.monotonic() > deadline:
                raise TimeoutError(f"stream timed out after {len(result.events)} events")
            if line == "":
                if "data" in fields:
                    event = SSEEvent(int(fields["id"]), json.loads(fields["data"]))
                    result.events.append(event)
                    if "retry" in fields:
                        result.retry_ms = int(fields["retry"])
                    fields = {}
                    if stop is not None and stop(event):
                        return result
                continue
            if line.startswith(":"):
                continue  # keep-alive comment
            key, _, value = line.partition(":")
            fields[key] = value.removeprefix(" ")
    result.closed_by_server = True
    return result


def is_status(*statuses: str) -> Callable[[SSEEvent], bool]:
    return lambda e: e.type == "run.status" and e.data["data"]["status"] in statuses


def after_n(n: int) -> Callable[[SSEEvent], bool]:
    """Stop condition: true on the n-th event seen."""
    seen = 0

    def stop(event: SSEEvent) -> bool:
        nonlocal seen
        seen += 1
        return seen >= n

    return stop


@dataclass
class ChatEvent:
    event: str
    data: dict[str, Any]


def read_chat(
    client: httpx.Client, url: str, body: Mapping[str, Any], timeout_s: float = 60
) -> list[ChatEvent]:
    """POSTs a co-working message and reads the reply stream (named SSE events) to the end."""
    events: list[ChatEvent] = []
    fields: dict[str, str] = {}
    with client.stream("POST", url, json=dict(body), timeout=timeout_s) as response:
        response.raise_for_status()
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "no-transform" in response.headers["cache-control"]
        for line in response.iter_lines():
            if line == "":
                if "data" in fields:
                    events.append(
                        ChatEvent(fields.get("event", "message"), json.loads(fields["data"]))
                    )
                fields = {}
                continue
            if line.startswith(":"):
                continue
            key, _, value = line.partition(":")
            fields[key] = value.removeprefix(" ")
    return events
