from datetime import datetime

from pydantic import BaseModel, Field

from app.models.patent import ConversionStatus, FileType, ModelScale
from app.models.review import ReviewState


class PatentUploadResponse(BaseModel):
    patent_id: int
    status: ConversionStatus
    message: str


class PatentConvertResponse(BaseModel):
    patent_id: int
    status: ConversionStatus


class ConversionWarning(BaseModel):
    """A single soft-warning emitted by the converter. Both fields are
    user-facing strings (Turkish, sourced from the converter's pattern
    dictionary in handlers.py)."""
    phase: str
    message: str
    details: str


class PatentStatusResponse(BaseModel):
    patent_id: int
    status: ConversionStatus
    error: str | None
    warnings: list[ConversionWarning] | None = None


class PatentListItem(BaseModel):
    id: int
    user_id: int
    uploaded_by: str
    model_filename: str | None
    file_type: FileType | None
    status: ConversionStatus = Field(validation_alias="conversion_status")
    uploaded_at: datetime
    locarno_main_class: str | None = None
    locarno_subclass: str | None = None
    has_thumbnail: bool = False
    warnings: list[ConversionWarning] | None = Field(
        default=None, validation_alias="conversion_warnings"
    )
    # For image-gen patents only: the ordered view labels (e.g. ["front",
    # "left"]) the model was generated from. Each maps to a stored source image
    # served at GET /patents/{id}/images/{view}. None for ZIP uploads.
    source_image_views: list[str] | None = None
    # Moderation context. On the public catalog this is always APPROVED; on a
    # design's detail page the owner/expert see the real state (and, when
    # REJECTED, the latest reason). None means "not exposed to this requester".
    review_state: ReviewState | None = None
    rejection_reason: str | None = None
    # Short-lived signed token so the owner/expert/admin can build a QR link to a
    # not-yet-public model (the /model route accepts it without a login). None on
    # the public catalog, where the plain /model URL already works.
    model_token: str | None = None

    class Config:
        from_attributes = True


class MySubmissionItem(BaseModel):
    """An owner's view of one of their own submissions.

    For UNDER_REVIEW designs every descriptive field is intentionally left null:
    the registration is obscured even from its owner during evaluation, who sees
    only that it exists and is under review."""
    id: int
    review_state: ReviewState
    submitted_at: datetime | None = None
    rejection_reason: str | None = None
    # Present for every state except UNDER_REVIEW (obscured).
    model_filename: str | None = None
    file_type: FileType | None = None
    conversion_status: ConversionStatus | None = None
    uploaded_at: datetime | None = None
    locarno_main_class: str | None = None
    locarno_subclass: str | None = None
    has_thumbnail: bool = False
    warnings: list[ConversionWarning] | None = None
    source_image_views: list[str] | None = None


class PatentMetadataUpdate(BaseModel):
    """Owner edit payload for a DRAFT/REJECTED design. All fields optional; only
    the supplied ones change. Locarno main/subclass must be supplied together."""
    design_name: str | None = Field(default=None, min_length=1, max_length=255)
    locarno_main_class: str | None = None
    locarno_subclass: str | None = None
    scale: ModelScale | None = None


class SubmitResponse(BaseModel):
    patent_id: int
    review_state: ReviewState


# -- Expert evaluation ---------------------------------------------------------

class ExpertSubmissionItem(BaseModel):
    """Full inspect payload for the expert evaluation queue/detail."""
    id: int
    user_id: int
    owner_username: str
    owner_email: str | None = None
    model_filename: str | None
    file_type: FileType | None
    conversion_status: ConversionStatus
    locarno_main_class: str | None = None
    locarno_subclass: str | None = None
    has_thumbnail: bool = False
    warnings: list[ConversionWarning] | None = None
    source_image_views: list[str] | None = None
    submitted_at: datetime
    uploaded_at: datetime


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class ReviewActionResponse(BaseModel):
    patent_id: int
    review_state: ReviewState