"""Expert evaluation queue: inspect pending submissions, approve or reject.

Gated at the package router level (EXPERT role). The queue is shared - any
expert can pick up any pending submission. A decision closes the current review
cycle: APPROVED makes the design public; REJECTED records a reason and reopens
the registration for the owner to edit and resubmit.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_expert_user
from app.api.routes.patents import _source_image_views
from app.db.session import get_db
from app.models.patent import Patent
from app.models.review import (
    DesignReview,
    ReviewDecision,
    ReviewState,
    effective_review_state,
    latest_review,
)
from app.models.user import User
from app.schemas.patent import ExpertSubmissionItem, RejectRequest, ReviewActionResponse

router = APIRouter(prefix="/submissions")


def _expert_item(patent: Patent, submitted_at: datetime) -> ExpertSubmissionItem:
    return ExpertSubmissionItem(
        id=patent.id,
        user_id=patent.user_id,
        owner_username=patent.user.username,
        owner_email=patent.user.email,
        model_filename=patent.model_filename,
        file_type=patent.file_type,
        conversion_status=patent.conversion_status,
        locarno_main_class=patent.locarno_main_class,
        locarno_subclass=patent.locarno_subclass,
        has_thumbnail=bool(patent.thumbnail_path),
        warnings=patent.conversion_warnings or None,
        source_image_views=_source_image_views(patent),
        submitted_at=submitted_at,
        uploaded_at=patent.uploaded_at,
    )


async def _get_pending_patent(patent_id: int, db: AsyncSession) -> Patent:
    """Load a patent that is currently UNDER_REVIEW (its latest cycle is
    PENDING), with owner + reviews. 404/409 otherwise."""
    stmt = (
        select(Patent)
        .where(Patent.id == patent_id)
        .options(selectinload(Patent.user), selectinload(Patent.reviews))
    )
    patent = (await db.execute(stmt)).scalar_one_or_none()
    if not patent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found.")
    if effective_review_state(patent.reviews) != ReviewState.UNDER_REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "This submission is not awaiting evaluation.")
    return patent


@router.get("", response_model=list[ExpertSubmissionItem])
async def list_pending_submissions(
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, description="Fuzzy name search (typo-tolerant via pg_trgm)."),
    locarno_main: str | None = Query(None, description="Filter by Locarno main class value."),
    locarno_subclass: str | None = Query(None, description="Filter by Locarno subclass value."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """The shared queue of submissions awaiting evaluation, oldest first.

    A design is awaiting evaluation when it has a PENDING review (approval is
    terminal, so an APPROVED review can never coexist with a PENDING one).
    Filterable by Locarno classification and by fuzzy name, like the catalog."""
    stmt = (
        select(Patent, DesignReview.submitted_at)
        .join(DesignReview, DesignReview.patent_id == Patent.id)
        .where(DesignReview.status == ReviewDecision.PENDING)
        .options(selectinload(Patent.user), selectinload(Patent.reviews))
    )

    if locarno_main:
        stmt = stmt.where(Patent.locarno_main_class == locarno_main)
    if locarno_subclass:
        stmt = stmt.where(Patent.locarno_subclass == locarno_subclass)

    q_clean = q.strip() if q else None
    if q_clean:
        await db.execute(text("SET LOCAL pg_trgm.word_similarity_threshold = 0.3"))
        stmt = stmt.where(Patent.model_filename.op("%>")(q_clean))
        stmt = stmt.order_by(
            func.word_similarity(q_clean, Patent.model_filename).desc(),
            DesignReview.submitted_at.asc(),
        )
    else:
        stmt = stmt.order_by(DesignReview.submitted_at.asc())

    stmt = stmt.limit(limit).offset(offset)
    rows = (await db.execute(stmt)).all()

    return [_expert_item(patent, submitted_at) for patent, submitted_at in rows]


@router.get("/{patent_id}", response_model=ExpertSubmissionItem)
async def get_pending_submission(patent_id: int, db: AsyncSession = Depends(get_db)):
    """Inspect a single submission awaiting evaluation."""
    patent = await _get_pending_patent(patent_id, db)
    latest = latest_review(patent.reviews)
    return _expert_item(patent, latest.submitted_at)


@router.post("/{patent_id}/approve", response_model=ReviewActionResponse)
async def approve_submission(
    patent_id: int,
    db: AsyncSession = Depends(get_db),
    expert: User = Depends(get_current_expert_user),
):
    """Approve the pending submission - the design becomes public."""
    patent = await _get_pending_patent(patent_id, db)
    review = latest_review(patent.reviews)

    review.status = ReviewDecision.APPROVED
    review.decided_at = datetime.now(timezone.utc)
    review.reviewed_by = expert.id
    await db.commit()

    return ReviewActionResponse(patent_id=patent.id, review_state=ReviewState.APPROVED)


@router.post("/{patent_id}/reject", response_model=ReviewActionResponse)
async def reject_submission(
    patent_id: int,
    payload: RejectRequest,
    db: AsyncSession = Depends(get_db),
    expert: User = Depends(get_current_expert_user),
):
    """Reject the pending submission with a reason. The registration reopens for
    the owner to edit (re-upload + metadata) and resubmit."""
    patent = await _get_pending_patent(patent_id, db)
    review = latest_review(patent.reviews)

    review.status = ReviewDecision.REJECTED
    review.rejection_reason = payload.reason.strip()
    review.decided_at = datetime.now(timezone.utc)
    review.reviewed_by = expert.id
    await db.commit()

    return ReviewActionResponse(patent_id=patent.id, review_state=ReviewState.REJECTED)