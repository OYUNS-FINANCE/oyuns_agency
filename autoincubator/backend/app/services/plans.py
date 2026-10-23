"""Business plans: persisted when the run completes; read and exported by the API."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.editor.schemas import BusinessPlan
from app.core.errors import NotFoundError
from app.db.models import BusinessPlanRow
from app.db.repositories import plans as plans_repo
from app.db.repositories import runs as runs_repo
from app.services import finance
from app.services.export.markdown import ENGINE_LABELS, render_markdown
from app.services.export.pdf import render_pdf
from app.services.schemas import EngineFormula, PlanResponse

FIRST_VERSION = 1
ExportFormat = Literal["md", "pdf"]


def _idea_uuid(plan: BusinessPlan) -> uuid.UUID | None:
    try:
        return uuid.UUID(plan.idea_id)
    except ValueError:
        return None  # the CLI selects by key, not by application id


async def persist(
    session: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID, plan: BusinessPlan
) -> bool:
    """Writes version 1 with its rendered Markdown, inside the caller's transaction (the
    worker's completion), so a completed run always has its plan."""
    markdown = render_markdown(plan, FIRST_VERSION, datetime.now(UTC).date())
    return await plans_repo.insert_version(
        session,
        run_id=run_id,
        user_id=user_id,
        idea_id=_idea_uuid(plan),
        version=FIRST_VERSION,
        plan=plan.model_dump(mode="json"),
        markdown=markdown,
    )


async def latest(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> BusinessPlanRow:
    if await runs_repo.get(session, run_id, user_id) is None:
        raise NotFoundError(f"run {run_id} not found")
    row = await plans_repo.latest(session, run_id, user_id)
    if row is None:
        raise NotFoundError(
            f"run {run_id} has no business plan yet; it is written when the run completes",
            code="plan_not_found",
        )
    return row


ENGINE_FORMULAS = [
    EngineFormula(
        key=key,
        label=ENGINE_LABELS[key],
        formula=formula,
        inputs=sorted(finance.DEPENDENCIES[key]),
    )
    for key, formula in finance.FORMULAS.items()
]


def to_response(row: BusinessPlanRow) -> PlanResponse:
    return PlanResponse(
        run_id=row.run_id,
        version=row.version,
        created_at=row.created_at,
        plan=BusinessPlan.model_validate(row.plan),
        engine_formulas=ENGINE_FORMULAS,
    )


def export_filename(row: BusinessPlanRow, fmt: ExportFormat) -> str:
    title = BusinessPlan.model_validate(row.plan).brief.opportunity.title
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "business-plan"
    return f"{slug}-v{row.version}.{fmt}"


def export(row: BusinessPlanRow, fmt: ExportFormat) -> bytes:
    if fmt == "md":
        return row.markdown.encode("utf-8")
    title = BusinessPlan.model_validate(row.plan).brief.opportunity.title
    return render_pdf(row.markdown, title)
