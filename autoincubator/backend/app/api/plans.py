"""The Phase-2 business plan: structured read and Markdown/PDF export."""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_session
from app.api.ratelimit import limit_api
from app.core.errors import ERROR_RESPONSES, ErrorResponse
from app.services import plans as plans_service
from app.services.plans import ExportFormat
from app.services.schemas import PlanResponse

router = APIRouter(prefix="/incubator", tags=["plans"], dependencies=[Depends(limit_api)])

Session = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]

MEDIA_TYPES: dict[ExportFormat, str] = {
    "md": "text/markdown; charset=utf-8",
    "pdf": "application/pdf",
}


@router.get("/runs/{run_id}/plan", response_model=PlanResponse, responses=ERROR_RESPONSES)
async def get_plan(run_id: uuid.UUID, session: Session, user_id: UserId) -> PlanResponse:
    """The latest plan version. 404 `plan_not_found` until the run has completed."""
    return plans_service.to_response(await plans_service.latest(session, user_id, run_id))


@router.get(
    "/runs/{run_id}/plan/export",
    response_class=Response,
    responses={
        **ERROR_RESPONSES,
        200: {
            "content": {
                "text/markdown": {"schema": {"type": "string"}},
                "application/pdf": {"schema": {"type": "string", "format": "binary"}},
            },
            "description": "The dossier as a file download.",
        },
        503: {"model": ErrorResponse, "description": "PDF rendering is unavailable"},
    },
)
async def export_plan(
    run_id: uuid.UUID,
    session: Session,
    user_id: UserId,
    format: Annotated[ExportFormat, Query()] = "md",
) -> Response:
    row = await plans_service.latest(session, user_id, run_id)
    # PDF rendering is CPU-bound (about a second): keep it off the event loop.
    body = await asyncio.to_thread(plans_service.export, row, format)
    filename = plans_service.export_filename(row, format)
    return Response(
        content=body,
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
