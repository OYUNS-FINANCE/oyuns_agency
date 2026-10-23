import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = pytest.mark.integration


async def test_health_against_real_services() -> None:
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"db": "ok", "redis": "ok"}
