"""Idea read models and conversions between idea versions and agent schemas."""

from __future__ import annotations

import uuid

from app.agents.analyst.schemas import MarketAnalysis
from app.agents.common.brief import IdeaBrief
from app.agents.scout.schemas import RawOpportunity
from app.agents.skeptic.schemas import CritiqueScorecard
from app.db.enums import CoworkMessageState, IdeaVersionSource
from app.db.models import CoworkMessage, Idea, IdeaVersion
from app.services.brief_patch import EditableBrief, PatchOperation
from app.services.schemas import CoworkMessageView, IdeaVersionView, IdeaView

STALE_REPLY_ERROR = "The reply was interrupted (the server stopped while generating it)."


def to_view(idea: Idea, version: IdeaVersion) -> IdeaView:
    return IdeaView(
        id=idea.id,
        key=idea.key,
        status=idea.status,
        rank=idea.rank,
        composite_score=float(idea.composite_score) if idea.composite_score is not None else None,
        version=version.version,
        version_source=version.source,
        score_stale=version.source == IdeaVersionSource.COWORK,
        merged_from=[uuid.UUID(i) for i in idea.merged_from],
        reject_reason=idea.reject_reason,
        title=str(version.opportunity["title"]),
        opportunity=RawOpportunity.model_validate(version.opportunity),
        analysis=MarketAnalysis.model_validate(version.analysis),
        critique=CritiqueScorecard.model_validate(version.critique),
    )


def to_version_view(version: IdeaVersion) -> IdeaVersionView:
    return IdeaVersionView(
        version=version.version,
        source=version.source,
        created_at=version.created_at,
        composite_score=float(version.composite_score),
        opportunity=RawOpportunity.model_validate(version.opportunity),
        analysis=MarketAnalysis.model_validate(version.analysis),
        critique=CritiqueScorecard.model_validate(version.critique),
        patch=[PatchOperation.model_validate(op) for op in version.patch]
        if version.patch
        else None,
        message_id=version.message_id,
    )


def to_message_view(
    message: CoworkMessage, applied_version: int | None, *, stale: bool = False
) -> CoworkMessageView:
    """`stale`: a pending reply older than the reply timeout; its process is gone."""
    state = message.state
    error = message.error
    if state == CoworkMessageState.PENDING and stale:
        state, error = CoworkMessageState.FAILED, STALE_REPLY_ERROR
    return CoworkMessageView(
        id=message.id,
        idea_id=message.idea_id,
        agent=message.agent.value,
        role=message.role.value,
        state=state.value,
        content=message.content,
        proposed_patch=[PatchOperation.model_validate(op) for op in message.proposed_patch]
        if message.proposed_patch
        else None,
        based_on_version=message.based_on_version,
        applied_version=applied_version,
        error=error,
        created_at=message.created_at,
    )


def editable(version: IdeaVersion) -> EditableBrief:
    return EditableBrief(
        opportunity=RawOpportunity.model_validate(version.opportunity),
        analysis=MarketAnalysis.model_validate(version.analysis),
    )


def to_brief(idea: Idea, version: IdeaVersion) -> IdeaBrief:
    """The idea at this version, in the shape the graph's resume payload carries."""
    return IdeaBrief(
        rank=idea.rank or 1,
        composite_score=max(1.0, float(version.composite_score)),
        opportunity=RawOpportunity.model_validate(version.opportunity),
        analysis=MarketAnalysis.model_validate(version.analysis),
        critique=CritiqueScorecard.model_validate(version.critique),
    )
