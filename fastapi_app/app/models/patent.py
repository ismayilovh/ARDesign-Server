import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.review import DesignReview
    from app.models.user import User


class FileType(str, enum.Enum):
    OBJ = "OBJ"
    STL = "STL"
    STP = "STP"
    IGES = "IGES"
    GLB = "GLB"
    FBX = "FBX"
    IMAGE = "IMAGE"   # source was one or more 2D images, generated via Hunyuan3D


class ModelScale(str, enum.Enum):
    """Source-file unit chosen at upload time. The converter CLI takes the
    lowercase form ('mm'/'cm'/'in'/'m'); the worker translates at the call
    site so the wire/DB representation stays uppercase like every other enum
    in this module."""
    MM = "MM"
    CM = "CM"
    IN = "IN"
    M = "M"


class ConversionStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"           # ZIP stored, awaiting user-triggered conversion
    QUEUED = "QUEUED"               # Celery task enqueued, waiting for a worker
    GENERATING = "GENERATING"       # Image-gen worker is running Hunyuan3D
    CONVERTING = "CONVERTING"       # Converter container is running
    CONVERTED = "CONVERTED"         # GLB ready
    FAILED = "FAILED"               # Conversion failed


class Patent(Base):
    __tablename__ = "patents_patent"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # --- ownership ---
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user: Mapped["User"] = relationship("User", back_populates="patents")

    # --- moderation / review lifecycle ---
    # The review state (draft/under-review/approved/rejected) is NOT stored on
    # the patent; it lives in design_reviews (one row per submit/decision cycle)
    # and is derived via app.models.review.effective_review_state(). A design is
    # public only when it has an APPROVED review.
    reviews: Mapped[List["DesignReview"]] = relationship(
        "DesignReview",
        back_populates="patent",
        cascade="all, delete-orphan",
        order_by="DesignReview.submitted_at",
        foreign_keys="DesignReview.patent_id",
    )

    # --- file metadata ---
    file_type: Mapped[Optional[FileType]] = mapped_column(
        Enum(FileType, name="filetype_enum"), nullable=True
    )
    model_filename: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, doc="User-supplied design name (sanitized for filesystem use)"
    )

    # --- registration form (Locarno design classification) ---
    # Stored as the string value of LocarnoMainClass/LocarnoSubclass enums; the
    # full hierarchy lives in app/data/locarno.py (5009 entries — too many for a
    # native Postgres enum, so we validate at the app layer).
    locarno_main_class: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="", doc="LocarnoMainClass enum value (e.g. SINIF_1)"
    )
    locarno_subclass: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default="", doc="LocarnoSubclass enum value"
    )
    scale: Mapped[ModelScale] = mapped_column(
        Enum(ModelScale, name="modelscale_enum"),
        nullable=False,
        default=ModelScale.M,
        server_default=ModelScale.M.value,
        doc="Source-file unit; meaningful for ZIP uploads, no-op for image-gen.",
    )

    # --- storage paths ---
    # Raw ZIP is stored here immediately on upload; never deleted
    zip_file_path: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, doc="Relative path to the original uploaded ZIP"
    )
    # Populated by the worker after successful extraction + conversion
    storage_path: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, doc="Folder containing extracted model files"
    )
    # ZIP flow: list[str] of extracted files (OBJ, MTL, textures…).
    # Image-gen flow: dict[str, str] mapping view label -> stored filename.
    related_files: Mapped[Optional[Any]] = mapped_column(
        JSON, nullable=True, doc="Extracted file list (ZIP) or view map (image-gen)"
    )
    glb_file_path: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, doc="Relative path to the converted GLB file"
    )
    thumbnail_path: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, doc="Relative path to the PNG thumbnail"
    )

    # --- task queue state ---
    conversion_status: Mapped[ConversionStatus] = mapped_column(
        Enum(ConversionStatus, name="conversionstatus_enum"),
        nullable=False,
        default=ConversionStatus.UPLOADED,
    )
    conversion_error: Mapped[Optional[str]] = mapped_column(
        String(2000), nullable=True, doc="Last error message from a failed conversion attempt"
    )
    # Soft warnings emitted by the converter while the conversion still
    # succeeded — e.g. an OBJ referenced an unsupported MTL line, or a texture
    # had no resolvable size at export time. Shape: list[{phase, message,
    # details}] where phase is "import" or "export". Surfaced in the UI as a ⚠
    # badge so the user knows to re-check the rendered model.
    conversion_warnings: Mapped[Optional[Any]] = mapped_column(
        JSON, nullable=True, doc="Parsed import/export warning list from the converter."
    )

    # --- timestamps ---
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<Patent id={self.id} status={self.conversion_status} user_id={self.user_id}>"
