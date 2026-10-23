import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import health
from app.api.health import CheckStatus, check_db, check_redis


def build_app(db: CheckStatus, redis: CheckStatus) -> FastAPI:
    app = FastAPI()
    app.include_router(health.router, prefix="/api")

    async def fake_db() -> CheckStatus:
        return db

    async def fake_redis() -> CheckStatus:
        return redis

    app.dependency_overrides[check_db] = fake_db
    app.dependency_overrides[check_redis] = fake_redis
    return app


@pytest.mark.parametrize(
    ("db", "redis", "expected_status"),
    [("ok", "ok", 200), ("error", "ok", 503), ("ok", "error", 503)],
)
async def test_health(db: CheckStatus, redis: CheckStatus, expected_status: int) -> None:
    app = build_app(db, redis)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == expected_status
    assert response.json() == {"db": db, "redis": redis}
