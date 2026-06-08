"""Admin design management: list every design across all users, delete any.

Gated at the package router level. Unlike the public catalog list, this is
not owner-scoped and surfaces owner identity plus the conversion error.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.patents import delete_patent_files
from app.db.session import get_db
from app.models.patent import ConversionStatus, Patent
from app.models.review import effective_review_state
from app.schemas.admin import AdminPatentItem

router = APIRouter(prefix="/patents")


@router.get("", response_model=list[AdminPatentItem])
async def list_all_patents(
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, description="Fuzzy name search (typo-tolerant via pg_trgm)."),
    locarno_main: str | None = Query(None),
    locarno_subclass: str | None = Query(None),
    conversion_status: ConversionStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    stmt = select(Patent).options(
        selectinload(Patent.user), selectinload(Patent.reviews)
    )

    if locarno_main:
        stmt = stmt.where(Patent.locarno_main_class == locarno_main)
    if locarno_subclass:
        stmt = stmt.where(Patent.locarno_subclass == locarno_subclass)
    if conversion_status:
        stmt = stmt.where(Patent.conversion_status == conversion_status)

    q_clean = q.strip() if q else None
    if q_clean:
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

    return [
        AdminPatentItem(
            id=p.id,
            user_id=p.user_id,
            owner_username=p.user.username,
            owner_email=p.user.email,
            model_filename=p.model_filename,
            file_type=p.file_type,
            status=p.conversion_status,
            review_state=effective_review_state(p.reviews),
            uploaded_at=p.uploaded_at,
            locarno_main_class=p.locarno_main_class,
            locarno_subclass=p.locarno_subclass,
            conversion_error=p.conversion_error,
        )
        for p in patents
    ]


@router.delete("/{patent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_any_patent(patent_id: int, db: AsyncSession = Depends(get_db)):
    patent = await db.get(Patent, patent_id)
    if not patent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patent not found.")

    delete_patent_files(patent)
    await db.delete(patent)
    await db.commit()
