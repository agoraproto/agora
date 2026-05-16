"""init schema

Revision ID: 0001
Revises:
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("did", sa.String(255), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_did", "users", ["did"])

    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("did", sa.String(255), nullable=False, unique=True),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("owner_did", sa.String(255), nullable=False),
        sa.Column("type", sa.String(32), nullable=False, server_default="service"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("public_endpoint", sa.Text(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("pricing", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("constraints", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("did_document", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("stake_eur", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("sponsor_did", sa.String(255), nullable=True),
        sa.Column("sponsor_signature", sa.Text(), nullable=True),
        sa.Column("trust_level", sa.String(32), nullable=False, server_default="probation"),
        sa.Column("webhook_secret_hash", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agents_did", "agents", ["did"])
    op.create_index("ix_agents_owner_did", "agents", ["owner_did"])
    op.create_index("ix_agents_status_type", "agents", ["status", "type"])

    op.create_table(
        "credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("issuer_did", sa.String(255), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("claim", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("requester_agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("provider_agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("task_spec", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="offered"),
        sa.Column("price_amount", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("price_currency", sa.String(8), nullable=False, server_default="EURC"),
        sa.Column("escrow_tx_hash", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("from_agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("to_agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("chain", sa.String(32), nullable=False, server_default="base-sepolia"),
        sa.Column("tx_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("reviewer_agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("reviewee_agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "disputes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("raised_by_agent_id", sa.Uuid(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("resolution", sa.JSON(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("disputes")
    op.drop_table("reviews")
    op.drop_table("payments")
    op.drop_table("jobs")
    op.drop_table("credentials")
    op.drop_index("ix_agents_status_type", table_name="agents")
    op.drop_index("ix_agents_owner_did", table_name="agents")
    op.drop_index("ix_agents_did", table_name="agents")
    op.drop_table("agents")
    op.drop_index("ix_users_did", table_name="users")
    op.drop_table("users")
