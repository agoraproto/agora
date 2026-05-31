"""Add signed_actions table for buyer-side nonce replay protection (Sprint 36d).

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signed_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_did", sa.String(length=255), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "actor_did",
            "intent",
            "nonce",
            name="uq_signed_actions_actor_intent_nonce",
        ),
    )
    op.create_index(
        "ix_signed_actions_actor_did",
        "signed_actions",
        ["actor_did"],
    )


def downgrade() -> None:
    op.drop_index("ix_signed_actions_actor_did", table_name="signed_actions")
    op.drop_table("signed_actions")
