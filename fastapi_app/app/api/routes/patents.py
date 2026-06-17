"""
Patent endpoints.

Upload flow  : POST /patents/upload      -> 202, patent stored as ZIP
Convert flow : POST /patents/{id}/convert -> 202, task dispatched to Celery
Status poll  : GET  /patents/{id}/status  -> current ConversionStatus
Model serve  : GET  /patents/{id}/model   -> streams GLB (only when CONVERTED)
Thumbnail    : GET  /patents/{id}/thumbnail -> streams PNG preview (best-effort)
List         : GET  /patents/             -> all patents ordered by upload date
Delete       : DELETE /patents/{id}       -> delete patent and files
"""
import os
import re
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_optional_user
from app.core.config import settings
from app.core.image_security import ALLOWED_MIMES as IMAGE_ALLOWED_MIMES, validate_and_reencode
from app.core.security import create_media_token, verify_media_token
from app.core.zip_security import validate_zip_upload
from app.data import locarno as locarno_cache
from app.db.session import get_db
from app.models.patent import ConversionStatus, FileType, ModelScale, Patent
from app.models.review import (
    DesignReview,
    ReviewDecision,
    ReviewState,
    effective_review_state,
    latest_review,
)
from app.models.user import User, UserRole
from app.schemas.patent import (
    MySubmissionItem,
    PatentConvertResponse,
    PatentListItem,
    PatentMetadataUpdate,
    PatentStatusResponse,
    PatentUploadResponse,
    SubmitResponse,
)
from app.worker.tasks import convert_patent_task, generate_from_image_task

router = APIRouter(prefix="/patents", tags=["patents"])

MODEL_EXTENSIONS: dict[str, str] = {
    ".obj": "OBJ",
    ".stl": "STL",
    ".stp": "STP",
    ".iges": "IGES",
    ".glb": "GLB",
    ".fbx": "FBX",
}

# Hunyuan3D inference presets — mirror gradio_app.py's Generation Mode and
# Decoding Mode radios so users get the same intuitive choices.
QUALITY_PRESETS: dict[str, int] = {"turbo": 5, "fast": 10, "standard": 30}
DETAIL_PRESETS: dict[str, int] = {"low": 196, "standard": 256, "high": 384}

# Canonical order for image-gen source views, so the detail page always shows
# them front → left → right → back regardless of the dict's insertion order.
VIEW_ORDER: dict[str, int] = {"front": 0, "left": 1, "right": 2, "back": 3}


def _source_image_views(patent: Patent) -> list[str] | None:
    """Ordered view labels for an image-gen patent, else None.

    `related_files` is a dict of {view: filename} for image-gen patents and a
    plain list of extracted files for ZIP uploads — only the former applies."""
    if patent.file_type != FileType.IMAGE or not isinstance(patent.related_files, dict):
        return None
    return sorted(patent.related_files.keys(), key=lambda v: VIEW_ORDER.get(v, 99))


def _patent_list_item(
    patent: Patent,
    review_state: ReviewState | None = None,
    rejection_reason: str | None = None,
    model_token: str | None = None,
) -> PatentListItem:
    """Build the public catalog/detail DTO from a Patent (with `user` loaded).

    `review_state`/`rejection_reason`/`model_token` are passed in by the caller
    (which knows whether the requester is allowed to see them); they stay None on
    anonymous catalog responses."""
    return PatentListItem(
        id=patent.id,
        user_id=patent.user_id,
        uploaded_by=patent.user.username,
        model_filename=patent.model_filename,
        file_type=patent.file_type,
        conversion_status=patent.conversion_status,
        uploaded_at=patent.uploaded_at,
        locarno_main_class=patent.locarno_main_class,
        locarno_subclass=patent.locarno_subclass,
        has_thumbnail=bool(patent.thumbnail_path),
        conversion_warnings=patent.conversion_warnings or None,
        source_image_views=_source_image_views(patent),
        review_state=review_state,
        rejection_reason=rejection_reason,
        model_token=model_token,
    )


def _latest_rejection_reason(patent: Patent) -> str | None:
    """The reason from the most recent cycle, but only while it's the active
    (REJECTED) state — so it surfaces on a rejected design and is cleared once
    resubmitted."""
    latest = latest_review(patent.reviews)
    if latest is not None and latest.status == ReviewDecision.REJECTED:
        return latest.rejection_reason
    return None


def _can_view_media(patent: Patent, user: User | None) -> bool:
    """Whether `user` (or anonymous, when None) may fetch this design's GLB /
    thumbnail / source images.

    APPROVED designs are public. Otherwise: admins and experts may see any state;
    the owner may preview their own DRAFT/REJECTED design, but during UNDER_REVIEW
    the registration is obscured even from its owner."""
    state = effective_review_state(patent.reviews)
    if state == ReviewState.APPROVED:
        return True
    if user is None:
        return False
    if user.role in (UserRole.ADMIN, UserRole.EXPERT):
        return True
    return user.id == patent.user_id and state in (ReviewState.DRAFT, ReviewState.REJECTED)


def _sanitize_filename(name: str) -> str:
    """Strip to alphanumeric, dash, underscore, dot. Replace spaces with underscores."""
    name = name.replace(" ", "_")
    return re.sub(r'[^\w\-.]', '', name)


async def _get_owned_patent(patent_id: int, user: User, db: AsyncSession) -> Patent:
    """Fetch a patent (with its review rows loaded) and verify ownership."""
    stmt = (
        select(Patent)
        .where(Patent.id == patent_id)
        .options(selectinload(Patent.reviews))
    )
    patent = (await db.execute(stmt)).scalar_one_or_none()
    if not patent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patent not found.")
    if patent.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your patent.")
    return patent


def delete_patent_files(patent: Patent) -> None:
    """Remove a patent's on-disk artifacts without touching anything else.

    The converted GLB and (for image-gen) the source images each live in their
    own per-patent directory, so we remove those directories whole. The uploaded
    ZIP, however, is a lone file inside the shared `uploads/user_X/` directory
    that also holds the user's other ZIPs — so we delete just that file, never
    its parent. Same for an optional thumbnail. Shared by the owner delete and
    the admin delete.
    """
    media_root = settings.media_root

    # Per-patent directories — safe to remove whole.
    if patent.glb_file_path:
        glb_dir = os.path.dirname(os.path.join(media_root, patent.glb_file_path))
        shutil.rmtree(glb_dir, ignore_errors=True)
    if patent.storage_path:
        shutil.rmtree(os.path.join(media_root, patent.storage_path), ignore_errors=True)

    # Lone files in shared directories — remove only the file.
    for rel_path in (patent.zip_file_path, patent.thumbnail_path):
        if rel_path:
            abs_path = os.path.join(media_root, rel_path)
            if os.path.isfile(abs_path):
                os.remove(abs_path)


# -- Upload --------------------------------------------------------------------

@router.post("/upload", response_model=PatentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_patent(
    file: UploadFile = File(...),
    design_name: str = Form(..., min_length=1, max_length=255),
    locarno_main_class: str = Form(...),
    locarno_subclass: str = Form(...),
    scale: ModelScale = Form(..., description="Source-file unit (MM/CM/IN/M)."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Phase-2 endpoint of the design-registration form: client submits the ZIP
    along with the Phase-1 fields (design_name + Locarno classification) in a
    single multipart request. Stored as UPLOADED; conversion is user-triggered
    via POST /{id}/convert.
    """
    await locarno_cache.validate_pair(db, locarno_main_class, locarno_subclass)

    safe_design_name = _sanitize_filename(design_name.strip())
    if not safe_design_name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "design_name must contain at least one filename-safe character.",
        )

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Only .zip files are accepted.")

    content = await file.read()

    # Full security validation (zip bomb, MIME, size, ratio, structure)
    model_ext, model_path_in_zip = validate_zip_upload(content, file.filename)
    file_type = FileType(MODEL_EXTENSIONS[model_ext])

    # -- Persist ZIP to disk ---------------------------------------------------
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = _sanitize_filename(file.filename)
    zip_rel = f"uploads/user_{current_user.id}/{timestamp}_{safe_name}"
    zip_abs = os.path.join(settings.media_root, zip_rel)

    os.makedirs(os.path.dirname(zip_abs), exist_ok=True)
    with open(zip_abs, "wb") as f:
        f.write(content)

    # -- Create DB record ------------------------------------------------------
    patent = Patent(
        user_id=current_user.id,
        zip_file_path=zip_rel,
        file_type=file_type,
        model_filename=safe_design_name,
        locarno_main_class=locarno_main_class,
        locarno_subclass=locarno_subclass,
        scale=scale,
        conversion_status=ConversionStatus.UPLOADED,
    )
    db.add(patent)
    await db.commit()
    await db.refresh(patent)

    return PatentUploadResponse(
        patent_id=patent.id,
        status=patent.conversion_status,
        message="Upload successful. POST /patents/{id}/convert to start conversion.",
    )


# -- Generate from image(s) ----------------------------------------------------

@router.post(
    "/generate",
    response_model=PatentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_from_images(
    front: UploadFile = File(..., description="Front view (required)"),
    left: UploadFile | None = File(None, description="Left view (optional)"),
    right: UploadFile | None = File(None, description="Right view (optional)"),
    back: UploadFile | None = File(None, description="Back view (optional)"),
    title: str | None = Form(None, description="Optional name for the generated model"),
    locarno_main_class: str = Form(...),
    locarno_subclass: str = Form(...),
    quality: str | None = Form(None, description="Quality preset: turbo|fast|standard"),
    detail: str | None = Form(None, description="Detail preset: low|standard|high"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Upload 1-4 view images under a Locarno classification. Validated, re-encoded
    to PNG, stored, and handed off to the `generate` Celery queue which routes to
    the host-native Hunyuan3D service. Returns 202 with QUEUED status; poll
    /status or /list for progress (QUEUED → GENERATING → QUEUED → CONVERTING →
    CONVERTED).

    The Hunyuan3D-2mv model was trained on front/left/back — 'right' is
    accepted but may be ignored or degrade quality.
    """
    # Same Locarno gate as the ZIP-upload path so every registered design,
    # however it was produced, carries a valid classification.
    await locarno_cache.validate_pair(db, locarno_main_class, locarno_subclass)

    # Resolve presets up-front so we fail fast on bad input.
    overrides: dict = {}
    if quality is not None:
        if quality not in QUALITY_PRESETS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"quality must be one of {list(QUALITY_PRESETS)}",
            )
        overrides["num_inference_steps"] = QUALITY_PRESETS[quality]
    if detail is not None:
        if detail not in DETAIL_PRESETS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"detail must be one of {list(DETAIL_PRESETS)}",
            )
        overrides["octree_resolution"] = DETAIL_PRESETS[detail]

    uploads_by_view = {"front": front, "left": left, "right": right, "back": back}
    uploads_by_view = {k: v for k, v in uploads_by_view.items() if v is not None}

    # Validate + re-encode each view up-front so we fail before writing anything.
    validated: dict[str, bytes] = {}
    for view_name, upload in uploads_by_view.items():
        if upload.content_type not in IMAGE_ALLOWED_MIMES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"'{view_name}' must be PNG, JPEG, or WebP (got {upload.content_type}).",
            )
        content = await upload.read()
        validated[view_name] = validate_and_reencode(content, view_name)

    # Persist to disk
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stem_raw = title.strip() if title else f"generated_{timestamp}"
    stem = _sanitize_filename(stem_raw) or f"generated_{timestamp}"
    storage_rel = f"uploads/user_{current_user.id}/{timestamp}_image_gen_{stem}"
    storage_abs = os.path.join(settings.media_root, storage_rel)
    os.makedirs(storage_abs, exist_ok=True)

    related: dict[str, str] = {}
    for view_name, png_bytes in validated.items():
        filename = f"{view_name}.png"
        with open(os.path.join(storage_abs, filename), "wb") as f:
            f.write(png_bytes)
        related[view_name] = filename

    # Create the Patent row as QUEUED — generation is dispatched immediately
    # (unlike the ZIP flow where the user manually triggers convert), but the
    # worker flips it to GENERATING when it actually picks the task up.
    patent = Patent(
        user_id=current_user.id,
        file_type=FileType.IMAGE,
        model_filename=stem,
        locarno_main_class=locarno_main_class,
        locarno_subclass=locarno_subclass,
        storage_path=storage_rel,
        related_files=related,
        conversion_status=ConversionStatus.QUEUED,
    )
    db.add(patent)
    await db.commit()
    await db.refresh(patent)

    generate_from_image_task.delay(patent.id, overrides or None)

    return PatentUploadResponse(
        patent_id=patent.id,
        status=patent.conversion_status,
        message=f"Generation started with {len(validated)} view(s).",
    )


# -- Trigger conversion --------------------------------------------------------

@router.post("/{patent_id}/convert", response_model=PatentConvertResponse, status_code=status.HTTP_202_ACCEPTED)
async def request_conversion(
    patent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Enqueue a Celery task to convert the model to GLB."""
    patent = await _get_owned_patent(patent_id, current_user, db)

    state = effective_review_state(patent.reviews)
    if state in (ReviewState.UNDER_REVIEW, ReviewState.APPROVED):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This registration is locked while under evaluation or after approval.",
        )

    if patent.conversion_status in (
        ConversionStatus.QUEUED,
        ConversionStatus.GENERATING,
        ConversionStatus.CONVERTING,
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Conversion already in progress.")

    if patent.conversion_status == ConversionStatus.CONVERTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Patent is already converted.")

    patent.conversion_status = ConversionStatus.QUEUED
    await db.commit()

    convert_patent_task.delay(patent_id)

    return PatentConvertResponse(patent_id=patent_id, status=ConversionStatus.QUEUED)


# -- Status polling ------------------------------------------------------------

@router.get("/{patent_id}/status", response_model=PatentStatusResponse)
async def get_status(
    patent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Poll the conversion status of a patent."""
    patent = await _get_owned_patent(patent_id, current_user, db)
    return PatentStatusResponse(
        patent_id=patent.id,
        status=patent.conversion_status,
        error=patent.conversion_error,
        warnings=patent.conversion_warnings or None,
    )


# -- List ----------------------------------------------------------------------

@router.get("/", response_model=list[PatentListItem])
async def list_patents(
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, description="Fuzzy name search (typo-tolerant via pg_trgm)."),
    locarno_main: str | None = Query(None, description="Filter by Locarno main class value."),
    locarno_subclass: str | None = Query(None, description="Filter by Locarno subclass value."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Browse the design catalog.

    Public endpoint (no auth) so anonymous visitors can see the catalog.
    Per-row owner-only actions (convert/delete) live behind their own auth-gated
    routes; this list only exposes data that's already viewable via the public
    /model endpoint.

    With `q` set, results are ordered by trigram similarity (best matches first)
    and filtered to rows whose `model_filename` is similar enough to `q`
    (pg_trgm `%` operator at the session's similarity threshold).

    Only APPROVED designs appear here: a design is public once an expert has
    approved it (it has an APPROVED review row). Drafts, under-review, and
    rejected designs are excluded.
    """
    # Public gate: the design must have an APPROVED review.
    stmt = (
        select(Patent)
        .where(Patent.reviews.any(DesignReview.status == ReviewDecision.APPROVED))
        .options(selectinload(Patent.user))
    )

    if locarno_main:
        stmt = stmt.where(Patent.locarno_main_class == locarno_main)
    if locarno_subclass:
        stmt = stmt.where(Patent.locarno_subclass == locarno_subclass)

    q_clean = q.strip() if q else None
    if q_clean:
        # Use word_similarity (not plain similarity) so long names like
        # "subway_train_interior" aren't penalized for their length —
        # word_similarity scores against the best matching window of the
        # target string and respects non-alphanumeric word boundaries.
        # SET LOCAL is scoped to this transaction only.
        await db.execute(text("SET LOCAL pg_trgm.word_similarity_threshold = 0.3"))
        stmt = stmt.where(Patent.model_filename.op("%>")(q_clean))
        stmt = stmt.order_by(
            func.word_similarity(q_clean, Patent.model_filename).desc(),
            Patent.uploaded_at.desc(),
        )
    else:
        stmt = stmt.order_by(Patent.uploaded_at.desc())

    stmt = stmt.limit(limit).offset(offset)

    patents = (await db.execute(stmt)).scalars().all()

    # Every row here is approved by construction.
    return [_patent_list_item(p, review_state=ReviewState.APPROVED) for p in patents]


# -- My submissions ------------------------------------------------------------

@router.get("/mine", response_model=list[MySubmissionItem])
async def list_my_submissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """The signed-in user's own submissions across every state.

    This is how an owner manages drafts, sees rejection reasons, and tracks
    approvals - the public catalog only shows approved designs. UNDER_REVIEW
    items are returned obscured (descriptive fields nulled): during evaluation
    the registration is hidden even from its owner."""
    stmt = (
        select(Patent)
        .where(Patent.user_id == current_user.id)
        .options(selectinload(Patent.reviews))
        .order_by(Patent.uploaded_at.desc())
    )
    patents = (await db.execute(stmt)).scalars().all()

    items: list[MySubmissionItem] = []
    for p in patents:
        state = effective_review_state(p.reviews)
        latest = latest_review(p.reviews)
        if state == ReviewState.UNDER_REVIEW:
            # Obscured: expose only that it exists and is under review.
            items.append(MySubmissionItem(
                id=p.id,
                review_state=state,
                submitted_at=latest.submitted_at if latest else None,
            ))
            continue
        items.append(MySubmissionItem(
            id=p.id,
            review_state=state,
            submitted_at=latest.submitted_at if latest else None,
            rejection_reason=_latest_rejection_reason(p),
            model_filename=p.model_filename,
            file_type=p.file_type,
            conversion_status=p.conversion_status,
            uploaded_at=p.uploaded_at,
            locarno_main_class=p.locarno_main_class,
            locarno_subclass=p.locarno_subclass,
            has_thumbnail=bool(p.thumbnail_path),
            warnings=p.conversion_warnings or None,
            source_image_views=_source_image_views(p),
        ))
    return items


# -- Submit for evaluation -----------------------------------------------------

@router.post("/{patent_id}/submit", response_model=SubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_for_evaluation(
    patent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Send a converted design to the expert evaluation queue.

    Allowed from DRAFT or REJECTED, and only once the model has CONVERTED. Opens
    a new review cycle (PENDING) and locks the registration from further edits
    until an expert decides."""
    patent = await _get_owned_patent(patent_id, current_user, db)

    state = effective_review_state(patent.reviews)
    if state == ReviewState.UNDER_REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "This registration is already under evaluation.")
    if state == ReviewState.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This registration is already approved.")
    if patent.conversion_status != ConversionStatus.CONVERTED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Convert the model before submitting it for evaluation.",
        )

    db.add(DesignReview(patent_id=patent.id, status=ReviewDecision.PENDING))
    await db.commit()

    return SubmitResponse(patent_id=patent.id, review_state=ReviewState.UNDER_REVIEW)


# -- Edit metadata -------------------------------------------------------------

@router.patch("/{patent_id}", response_model=PatentListItem)
async def update_patent_metadata(
    patent_id: int,
    payload: PatentMetadataUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Edit a DRAFT or REJECTED design's metadata (name / Locarno / scale).

    Locked while UNDER_REVIEW or after APPROVED. A rejected design stays REJECTED
    (its reason remains visible as guidance) until the owner resubmits."""
    patent = await _get_owned_patent(patent_id, current_user, db)

    state = effective_review_state(patent.reviews)
    if state not in (ReviewState.DRAFT, ReviewState.REJECTED):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This registration is locked while under evaluation or after approval.",
        )

    # Locarno main/subclass must move together so the pair stays valid.
    if (payload.locarno_main_class is None) != (payload.locarno_subclass is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Provide both locarno_main_class and locarno_subclass together.",
        )
    if payload.locarno_main_class is not None and payload.locarno_subclass is not None:
        await locarno_cache.validate_pair(db, payload.locarno_main_class, payload.locarno_subclass)
        patent.locarno_main_class = payload.locarno_main_class
        patent.locarno_subclass = payload.locarno_subclass

    if payload.design_name is not None:
        safe_design_name = _sanitize_filename(payload.design_name.strip())
        if not safe_design_name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "design_name must contain at least one filename-safe character.",
            )
        patent.model_filename = safe_design_name

    if payload.scale is not None:
        patent.scale = payload.scale

    await db.commit()
    await db.refresh(patent, attribute_names=["user"])

    return _patent_list_item(
        patent, review_state=state, rejection_reason=_latest_rejection_reason(patent)
    )


# -- Re-upload model (replace the file) ----------------------------------------

@router.post("/{patent_id}/reupload", response_model=PatentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def reupload_patent(
    patent_id: int,
    file: UploadFile = File(...),
    scale: ModelScale = Form(..., description="Source-file unit (MM/CM/IN/M)."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Replace the model file of a DRAFT/REJECTED design with a new ZIP.

    Used after a rejection to upload a corrected model. Old artifacts (GLB,
    thumbnail, extracted files) are removed and conversion resets to UPLOADED;
    the owner reconverts and then resubmits. Locked while UNDER_REVIEW/APPROVED."""
    patent = await _get_owned_patent(patent_id, current_user, db)

    state = effective_review_state(patent.reviews)
    if state not in (ReviewState.DRAFT, ReviewState.REJECTED):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This registration is locked while under evaluation or after approval.",
        )

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Only .zip files are accepted.")

    content = await file.read()
    model_ext, _ = validate_zip_upload(content, file.filename)
    file_type = FileType(MODEL_EXTENSIONS[model_ext])

    # Remove the previous artifacts before pointing the record at the new ZIP.
    delete_patent_files(patent)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = _sanitize_filename(file.filename)
    zip_rel = f"uploads/user_{current_user.id}/{timestamp}_{safe_name}"
    zip_abs = os.path.join(settings.media_root, zip_rel)
    os.makedirs(os.path.dirname(zip_abs), exist_ok=True)
    with open(zip_abs, "wb") as f:
        f.write(content)

    # Reset to a fresh, unconverted state.
    patent.zip_file_path = zip_rel
    patent.file_type = file_type
    patent.scale = scale
    patent.storage_path = None
    patent.related_files = None
    patent.glb_file_path = None
    patent.thumbnail_path = None
    patent.conversion_warnings = None
    patent.conversion_error = None
    patent.conversion_status = ConversionStatus.UPLOADED
    await db.commit()

    return PatentUploadResponse(
        patent_id=patent.id,
        status=patent.conversion_status,
        message="Re-upload successful. POST /patents/{id}/convert to start conversion.",
    )


# -- Detail --------------------------------------------------------------------

@router.get("/{patent_id}", response_model=PatentListItem)
async def get_patent(
    patent_id: int,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Fetch a single patent's catalog metadata for its detail page.

    Visibility follows the review state:
    - APPROVED designs are public (anonymous visitors and QR scans included).
    - Admins and experts may open a design in any state.
    - DRAFT / REJECTED designs are also visible to their owner (so they can
      preview and manage them).
    - UNDER_REVIEW designs are obscured from their owner (403); only admins and
      experts may open them.
    Anything else returns 404 so non-public designs aren't enumerable.
    """
    stmt = (
        select(Patent)
        .where(Patent.id == patent_id)
        .options(selectinload(Patent.user), selectinload(Patent.reviews))
    )
    patent = (await db.execute(stmt)).scalar_one_or_none()
    if not patent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patent not found.")

    state = effective_review_state(patent.reviews)
    if state == ReviewState.APPROVED:
        # Public: the plain /model URL already works, no capability token needed.
        return _patent_list_item(patent, review_state=state)

    # A signed, short-lived token so the QR link to a not-yet-public model
    # resolves for an unauthenticated scanner. Only minted once converted.
    media_token = (
        create_media_token(patent.id)
        if patent.conversion_status == ConversionStatus.CONVERTED
        else None
    )

    # Admins and experts can see everything.
    if user is not None and user.role in (UserRole.ADMIN, UserRole.EXPERT):
        return _patent_list_item(
            patent, review_state=state,
            rejection_reason=_latest_rejection_reason(patent), model_token=media_token,
        )

    is_owner = user is not None and user.id == patent.user_id
    if is_owner:
        if state == ReviewState.UNDER_REVIEW:
            # Obscured even from the owner during evaluation.
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This registration is under evaluation.")
        return _patent_list_item(
            patent, review_state=state,
            rejection_reason=_latest_rejection_reason(patent), model_token=media_token,
        )

    raise HTTPException(status.HTTP_404_NOT_FOUND, "Patent not found.")


# -- Serve GLB -----------------------------------------------------------------

@router.get("/{patent_id}/model")
async def serve_model(
    patent_id: int,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
    token: str | None = Query(None, description="Signed media token (used by QR links)."),
):
    """Stream the converted GLB file.

    Public for APPROVED designs (so QR-code scans work without a token); for
    other states only the owner (DRAFT/REJECTED), experts, admins, or a holder
    of a valid signed media token may fetch it. The token lets an owner preview
    a draft in AR by scanning its QR. See _can_view_media / verify_media_token."""
    stmt = (
        select(Patent)
        .where(Patent.id == patent_id)
        .options(selectinload(Patent.reviews))
    )
    patent = (await db.execute(stmt)).scalar_one_or_none()
    has_access = patent is not None and (
        _can_view_media(patent, user) or (token is not None and verify_media_token(token, patent.id))
    )
    if not has_access:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patent not found.")

    if patent.conversion_status != ConversionStatus.CONVERTED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Model not ready. Current status: {patent.conversion_status}",
        )

    glb_abs = os.path.join(settings.media_root, patent.glb_file_path)
    if not os.path.exists(glb_abs):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "GLB file missing from storage.")

    return FileResponse(
        glb_abs,
        media_type="model/gltf-binary",
        filename=f"{patent.model_filename}.glb",
    )


# -- Serve thumbnail -----------------------------------------------------------

@router.get("/{patent_id}/thumbnail")
async def serve_thumbnail(
    patent_id: int,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Stream the PNG thumbnail. Public for APPROVED designs (like /model) so the
    browse grid and QR-scanned clients can show a preview; otherwise restricted
    to the owner/expert/admin (see _can_view_media). 404 when the patent never
    produced a thumbnail (the render is best-effort) — callers fall back."""
    stmt = (
        select(Patent)
        .where(Patent.id == patent_id)
        .options(selectinload(Patent.reviews))
    )
    patent = (await db.execute(stmt)).scalar_one_or_none()
    if not patent or not patent.thumbnail_path or not _can_view_media(patent, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thumbnail not found.")

    thumb_abs = os.path.join(settings.media_root, patent.thumbnail_path)
    if not os.path.exists(thumb_abs):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thumbnail missing from storage.")

    return FileResponse(thumb_abs, media_type="image/png")


# -- Serve source image (image-gen only) --------------------------------------

@router.get("/{patent_id}/images/{view}")
async def serve_source_image(
    patent_id: int,
    view: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    """Stream one of the reference photos an image-gen design was built from.

    Public for APPROVED designs so the detail page can show source views;
    otherwise restricted to the owner/expert/admin (see _can_view_media). `view`
    is a label from the patent's related_files map (front/left/right/back). 404
    for ZIP uploads or unknown views."""
    stmt = (
        select(Patent)
        .where(Patent.id == patent_id)
        .options(selectinload(Patent.reviews))
    )
    patent = (await db.execute(stmt)).scalar_one_or_none()
    if (
        not patent
        or patent.file_type != FileType.IMAGE
        or not patent.storage_path
        or not isinstance(patent.related_files, dict)
        or not _can_view_media(patent, user)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source image not found.")

    filename = patent.related_files.get(view)
    if not filename:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source image not found.")

    img_abs = os.path.join(settings.media_root, patent.storage_path, filename)
    if not os.path.exists(img_abs):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source image missing from storage.")

    return FileResponse(img_abs, media_type="image/png")


# -- Delete --------------------------------------------------------------------

@router.delete("/{patent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patent(
    patent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete a patent record and its files from disk.

    Blocked while the registration is UNDER_REVIEW (it's locked during
    evaluation). Admins can still delete any design via the admin route."""
    patent = await _get_owned_patent(patent_id, current_user, db)

    if effective_review_state(patent.reviews) == ReviewState.UNDER_REVIEW:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This registration is locked while under evaluation.",
        )

    delete_patent_files(patent)

    await db.delete(patent)
    await db.commit()
