"""Link Jobs back to Listings (Sprint 10c)

Adds `listing_id` to the `jobs` table so an on-chain payment for a
marketplace listing can be reconciled with its origin. Used by the
delivery endpoint to gate access to digital_content.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("listing_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_jobs_listing_id", "jobs", ["listing_id"], unique=False)
    op.create_foreign_key(
        "fk_jobs_listing_id",
        "jobs",
        "listings",
        ["listing_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_jobs_listing_id", "jobs", type_="foreignkey")
    op.drop_index("ix_jobs_listing_id", table_name="jobs")
    op.drop_column("jobs", "listing_id")
