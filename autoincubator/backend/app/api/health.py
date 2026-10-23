from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.deps import get_engine, get_redis
from app.core.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)

CheckStatus = Literal["ok", "error"]


class HealthResponse(BaseModel):
    db: CheckStatus
    redis: CheckStatus


async def check_db(engine: Annotated[AsyncEngine, Depends(get_engine)]) -> CheckStatus:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        log.warning("health.db_failed", exc_info=True)
        return "error"
    return "ok"


async def check_redis(redis: Annotated["Redis", Depends(get_redis)]) -> CheckStatus:
    try:
        await redis.ping()
    except Exception:
        log.warning("health.redis_failed", exc_info=True)
        return "error"
    return "ok"


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response,
    db: Annotated[CheckStatus, Depends(check_db)],
    redis: Annotated[CheckStatus, Depends(check_redis)],
) -> HealthResponse:
    if db != "ok" or redis != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(db=db, redis=redis)
