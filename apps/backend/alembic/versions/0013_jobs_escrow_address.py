"""Add jobs.escrow_contract_address (Sprint 36g).

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Record which AgoraEscrow contract a given on-chain Job was created
    # against. Legacy jobs (created before this migration) stay NULL —
    # the chain_watcher will ignore them rather than polling them against
    # the current (possibly V2) contract and tripping unknown_status.
    op.add_column(
        "jobs",
        sa.Column("escrow_contract_address", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_jobs_escrow_contract_address",
        "jobs",
        ["escrow_contract_address"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_escrow_contract_address", table_name="jobs")
    op.drop_column("jobs", "escrow_contract_address")
