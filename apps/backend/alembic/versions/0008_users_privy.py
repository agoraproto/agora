"""Add Privy auth fields to users (Sprint 10d)

Adds `privy_user_id` (the stable Privy identifier returned in the JWT
`sub` claim) and `primary_wallet` (the EVM address from the user's Privy
embedded wallet, or a linked external wallet). Both nullable so seeded
users from earlier sprints remain valid.

A unique index on privy_user_id is created so we can upsert idempotently
when a returning user logs in.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("privy_user_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("primary_wallet", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_users_privy_user_id",
        "users",
        ["privy_user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_privy_user_id", table_name="users")
    op.drop_column("users", "primary_wallet")
    op.drop_column("users", "privy_user_id")
