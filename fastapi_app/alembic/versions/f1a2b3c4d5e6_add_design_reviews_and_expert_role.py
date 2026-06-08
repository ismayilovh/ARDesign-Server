"""add design_reviews table + EXPERT role

Revision ID: f1a2b3c4d5e6
Revises: b2c3d4e5f6a7
Create Date: 2026-06-08 00:00:00.000000

Introduces the expert-evaluation workflow. Adds the EXPERT application role and
a `design_reviews` table that records each submit/decision cycle for a design
(one row per submission, so reject -> resubmit keeps a full audit trail). The
patent's effective moderation state (DRAFT / UNDER_REVIEW / APPROVED / REJECTED)
is derived from these rows, not stored on patents_patent.

Public visibility moves from `conversion_status == CONVERTED` to "has an
APPROVED review", so existing CONVERTED designs are backfilled with an APPROVED
review row to keep the public catalog unchanged.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- 1. EXPERT role -------------------------------------------------------
    # Postgres requires ALTER TYPE ... ADD VALUE to run outside a transaction.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole_enum ADD VALUE IF NOT EXISTS 'EXPERT'")

    # -- 2. design_reviews table ----------------------------------------------
    # create_table emits CREATE TYPE for this enum on its own (the column
    # references it), so we must NOT also create it explicitly or the two
    # collide with "type already exists".
    decision_enum = sa.Enum("PENDING", "APPROVED", "REJECTED", name="reviewdecision_enum")

    op.create_table(
        "design_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("patent_id", sa.Integer(), nullable=False),
        sa.Column("status", decision_enum, nullable=False, server_default="PENDING"),
        sa.Column("rejection_reason", sa.String(length=2000), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["patent_id"], ["patents_patent.id"],
            name="fk_design_reviews_patent", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users_user.id"],
            name="fk_design_reviews_reviewer", ondelete="SET NULL",
        ),
    )
    op.create_index("ix_design_reviews_patent_id", "design_reviews", ["patent_id"])

    # -- 3. Backfill: existing CONVERTED designs stay public ------------------
    # Give each already-converted patent an APPROVED review so it remains in the
    # public catalog under the new "has an APPROVED review" gate. submitted_at
    # mirrors the original upload time; decided_at marks the migration moment.
    op.execute(
        """
        INSERT INTO design_reviews (patent_id, status, submitted_at, decided_at)
        SELECT id, 'APPROVED', uploaded_at, now()
        FROM patents_patent
        WHERE conversion_status = 'CONVERTED'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_design_reviews_patent_id", table_name="design_reviews")
    op.drop_table("design_reviews")
    sa.Enum(name="reviewdecision_enum").drop(op.get_bind(), checkfirst=True)
    # Postgres has no syntax to drop a single enum value, so EXPERT is left in
    # userrole_enum — an unused member is harmless.