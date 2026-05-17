"""webhook delivery queue (Sprint 6 / ADR 008)

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STATUS = sa.Enum(
    "pending", "delivering", "delivered", "failed", "exhausted",
    name="webhookdeliverystatus",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent_did", sa.String(255), nullable=False, index=True),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("agents.id"),
            nullable=True,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("jobs.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("event_type", sa.String(64), nullable=False, index=True),
        sa.Column("endpoint_url", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", _STATUS, nullable=False, server_default="pending", index=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_response_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_webhook_deliveries_due",
        "webhook_deliveries",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_due", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    sa.Enum(name="webhookdeliverystatus").drop(op.get_bind(), checkfirst=True)
