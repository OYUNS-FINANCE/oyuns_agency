from app.worker.main import WorkerSettings, ping


async def test_ping_returns_pong() -> None:
    assert await ping({"job_id": "test"}) == "pong"


def test_ping_is_registered() -> None:
    assert ping in WorkerSettings.functions
