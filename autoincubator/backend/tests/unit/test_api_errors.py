"""Every API failure uses the same error shape."""

from collections.abc import AsyncIterator

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_arq, get_redis, get_session
from app.core.errors import NotFoundError
from app.main import create_app
from tests.fakes import FakeRedis


async def _no_session() -> AsyncIterator[None]:
    yield None


def _app() -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_session] = _no_session
    app.dependency_overrides[get_arq] = lambda: None
    app.dependency_overrides[get_redis] = lambda: FakeRedis()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail")

    @app.get("/missing")
    async def missing() -> None:
        raise NotFoundError("run x not found", details={"run_id": "x"})

    return app


async def _client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_semantic_validation_error_is_422_with_details() -> None:
    async with await _client(_app()) as client:
        r = await client.post("/api/incubator/runs", json={"mode": "seeded"})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    assert "requires a seed" in body["details"][0]["msg"]


async def test_schema_validation_error_is_422() -> None:
    async with await _client(_app()) as client:
        r = await client.post("/api/incubator/runs", json={"mode": "nope"})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["loc"] == ["body", "mode"]


async def test_app_error_unknown_route_and_unhandled_error() -> None:
    async with await _client(_app()) as client:
        missing = await client.get("/missing")
        unknown = await client.get("/api/nope")
        boom = await client.get("/boom")
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {"code": "not_found", "message": "run x not found", "details": {"run_id": "x"}}
    }
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "not_found"
    assert boom.status_code == 500
    assert boom.json() == {
        "error": {"code": "internal_error", "message": "Internal server error", "details": None}
    }
