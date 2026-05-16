"""reputation cache + dispute resolution columns

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("reputation_score", sa.Numeric(3, 2), nullable=True))
        batch.add_column(sa.Column("reputation_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("jobs_completed", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("reviews") as batch:
        batch.add_column(sa.Column("aggregate_score", sa.Numeric(3, 2), nullable=False, server_default="0"))
        batch.alter_column("signature", server_default="", existing_type=sa.Text())

    with op.batch_alter_table("disputes") as batch:
        batch.add_column(sa.Column("resolved_by", sa.String(64), nullable=True))

    op.create_index("ix_reviews_reviewee_agent_id", "reviews", ["reviewee_agent_id"])


def downgrade() -> None:
    op.drop_index("ix_reviews_reviewee_agent_id", table_name="reviews")
    with op.batch_alter_table("disputes") as batch:
        batch.drop_column("resolved_by")
    with op.batch_alter_table("reviews") as batch:
        batch.drop_column("aggregate_score")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("jobs_completed")
        batch.drop_column("reputation_count")
        batch.drop_column("reputation_score")
