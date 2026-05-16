"""ledger tables + extended job status

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ledger_balances",
        sa.Column("agent_did", sa.String(255), primary_key=True),
        sa.Column("currency", sa.String(8), primary_key=True),
        sa.Column("available", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("in_escrow", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent_did", sa.String(255), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("delta_available", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("delta_escrow", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ledger_entries_agent_did", "ledger_entries", ["agent_did"])
    op.create_index("ix_ledger_entries_job_id", "ledger_entries", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_ledger_entries_job_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_agent_did", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_table("ledger_balances")
