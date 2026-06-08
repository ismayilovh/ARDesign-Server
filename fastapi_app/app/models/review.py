import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.patent import Patent
    from app.models.user import User


class ReviewDecision(str, enum.Enum):
    """Outcome of a single submit/decision cycle stored in design_reviews."""
    PENDING = "PENDING"     # Submitted, awaiting an expert
    APPROVED = "APPROVED"   # Expert approved -> design becomes public (terminal)
    REJECTED = "REJECTED"   # Expert rejected with a reason -> owner may edit & resubmit


class ReviewState(str, enum.Enum):
    """The patent's effective, derived moderation state (not stored). Computed
    from its design_reviews rows and surfaced to the API/UI."""
    DRAFT = "DRAFT"                 # Never submitted (or re-opened); owner previews privately
    UNDER_REVIEW = "UNDER_REVIEW"   # Latest cycle is PENDING; locked + obscured from owner
    APPROVED = "APPROVED"           # Has an APPROVED review; public
    REJECTED = "REJECTED"           # Latest cycle was REJECTED; owner may edit & resubmit


class DesignReview(Base):
    """One submit/decision cycle for a design. A patent accumulates one row per
    submission so the full audit trail (every reject + resubmit) is preserved."""
    __tablename__ = "design_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    patent_id: Mapped[int] = mapped_column(
        ForeignKey("patents_patent.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ReviewDecision] = mapped_column(
        Enum(ReviewDecision, name="reviewdecision_enum"),
        nullable=False,
        default=ReviewDecision.PENDING,
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(
        String(2000), nullable=True, doc="Expert's reason; set only when status is REJECTED."
    )

    # --- timestamps / audit ---
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        doc="When the owner submitted this cycle for evaluation.",
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When an expert approved/rejected."
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users_user.id", ondelete="SET NULL"),
        nullable=True,
        doc="Expert who decided this cycle (audit).",
    )

    # --- relationships ---
    patent: Mapped["Patent"] = relationship(
        "Patent", back_populates="reviews", foreign_keys=[patent_id]
    )
    reviewer: Mapped[Optional["User"]] = relationship("User", foreign_keys=[reviewed_by])

    def __repr__(self) -> str:
        return f"<DesignReview id={self.id} patent_id={self.patent_id} status={self.status}>"


def latest_review(reviews: Iterable["DesignReview"]) -> Optional["DesignReview"]:
    """The most recent cycle by submission time, or None if never submitted."""
    rows = list(reviews)
    if not rows:
        return None
    return max(rows, key=lambda r: r.submitted_at)


def effective_review_state(reviews: Iterable["DesignReview"]) -> ReviewState:
    """Derive a patent's moderation state from its review rows.

    APPROVED is terminal, so a single approved cycle wins outright. Otherwise the
    latest cycle decides: PENDING -> UNDER_REVIEW, REJECTED -> REJECTED, and no
    rows at all -> DRAFT."""
    rows = list(reviews)
    if any(r.status == ReviewDecision.APPROVED for r in rows):
        return ReviewState.APPROVED
    latest = latest_review(rows)
    if latest is None:
        return ReviewState.DRAFT
    if latest.status == ReviewDecision.PENDING:
        return ReviewState.UNDER_REVIEW
    if latest.status == ReviewDecision.REJECTED:
        return ReviewState.REJECTED
    return ReviewState.DRAFT