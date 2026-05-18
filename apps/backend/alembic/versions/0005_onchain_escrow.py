"""On-chain escrow columns (Sprint 9 / USDC on Base)

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Jobs settled on AgoraEscrow expose a uint256 jobId from createJob().
    # We mirror it here so the backend can resolve approve/dispute calls.
    op.add_column(
        "jobs",
        sa.Column("onchain_job_id", sa.Numeric(78, 0), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("release_tx_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "settlement_mode",
            sa.String(16),
            nullable=False,
            server_default="offchain",
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "chain",
            sa.String(32),
            nullable=False,
            server_default="none",
        ),
    )
    op.create_index(
        "ix_jobs_onchain_job_id",
        "jobs",
        ["onchain_job_id"],
        unique=False,
    )

    # Agents need a payout wallet on the settlement chain.
    op.add_column(
        "agents",
        sa.Column("payout_wallet", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "payout_wallet")
    op.drop_index("ix_jobs_onchain_job_id", table_name="jobs")
    op.drop_column("jobs", "chain")
    op.drop_column("jobs", "settlement_mode")
    op.drop_column("jobs", "release_tx_hash")
    op.drop_column("jobs", "onchain_job_id")
