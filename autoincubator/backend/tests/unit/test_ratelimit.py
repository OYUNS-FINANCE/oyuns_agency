"""Rate limiting of public endpoints."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.api.deps import get_app_settings, get_arq, get_redis, get_session
from app.api.ratelimit import client_ip
from app.core.config import Settings
from app.main import create_app
from tests.fakes import BrokenRedis, FakeRedis


def _request(headers: dict[str, str], peer: str = "10.0.0.9") -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (peer, 1234),
        }
    )


def test_client_ip_ignores_forwarded_for_unless_proxies_are_trusted() -> None:
    req = _request({"x-forwarded-for": "6.6.6.6"})
    assert client_ip(req, 0) == "10.0.0.9"


def test_client_ip_takes_the_entry_the_trusted_proxy_appended() -> None:
    # client-supplied spoof first, then what each of two trusted proxies appended
    req = _request({"x-forwarded-for": "6.6.6.6, 203.0.113.7, 172.18.0.3"})
    assert client_ip(req, 2) == "203.0.113.7"
    assert client_ip(req, 1) == "172.18.0.3"
    assert client_ip(req, 5) == "10.0.0.9"  # fewer hops than configured: do not trust it


async def _no_session() -> AsyncIterator[None]:
    yield None


def _app(redis: Any, **settings_kw: Any) -> FastAPI:
    settings = Settings(_env_file=None, **settings_kw)
    app = create_app()
    app.dependency_overrides[get_session] = _no_session
    app.dependency_overrides[get_arq] = lambda: None
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_app_settings] = lambda: settings
    return app


async def _post_invalid(app: FastAPI) -> int:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        return (await client.post("/api/incubator/runs", json={"mode": "seeded"})).status_code


async def test_create_run_is_limited_per_hour_with_retry_after() -> None:
    app = _app(FakeRedis(), rate_limit_runs_per_hour=2)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        codes = [
            (await client.post("/api/incubator/runs", json={"mode": "seeded"})).status_code
            for _ in range(2)
        ]
        blocked = await client.post("/api/incubator/runs", json={"mode": "seeded"})
    assert codes == [422, 422]  # allowed through to validation
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert blocked.json()["error"]["details"]["limit"] == 2
    assert 0 < int(blocked.headers["retry-after"]) <= 3600


async def test_limits_are_per_client() -> None:
    redis = FakeRedis()
    app = _app(redis, rate_limit_runs_per_hour=1, trusted_proxy_hops=1)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        a = {"x-forwarded-for": "1.1.1.1"}
        b = {"x-forwarded-for": "2.2.2.2"}
        body = {"mode": "seeded"}
        assert (await client.post("/api/incubator/runs", json=body, headers=a)).status_code == 422
        assert (await client.post("/api/incubator/runs", json=body, headers=b)).status_code == 422
        assert (await client.post("/api/incubator/runs", json=body, headers=a)).status_code == 429


async def test_disabled_limiter_lets_everything_through() -> None:
    app = _app(FakeRedis(), rate_limit_enabled=False, rate_limit_runs_per_hour=1)
    assert [await _post_invalid(app) for _ in range(3)] == [422, 422, 422]


async def test_redis_outage_fails_open() -> None:
    app = _app(BrokenRedis(), rate_limit_runs_per_hour=1)
    assert [await _post_invalid(app) for _ in range(3)] == [422, 422, 422]


async def test_health_and_stream_are_not_limited_by_the_default_limiter() -> None:
    redis = FakeRedis()
    app = _app(redis, rate_limit_api_per_minute=1)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        for _ in range(3):
            await client.get("/api/health")
    assert not any(key.startswith("rl:api") for key in redis.counts)
