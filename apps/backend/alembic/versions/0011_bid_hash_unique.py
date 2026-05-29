"""Add UNIQUE(request_id, bid_hash) on bids (Sprint 34b)

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Sprint 34b: prevent identical-content bids from being submitted
    # twice (even with a different nonce). The provider should never have
    # a reason to submit the same canonical signed_payload twice; this
    # constraint enforces it at the DB level.
    op.create_unique_constraint(
        "uq_bids_request_bid_hash",
        "bids",
        ["request_id", "bid_hash"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_bids_request_bid_hash", "bids", type_="unique")
