"""Add RFQ service requests and bids (Sprint 31)

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("buyer_did", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=True),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("max_price_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.Column("accepted_bid_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("max_price_micro_usdc <= 10000", name="ck_service_requests_max_price"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_requests_buyer_did", "service_requests", ["buyer_did"])
    op.create_index("ix_service_requests_capability", "service_requests", ["capability"])
    op.create_index("ix_service_requests_status", "service_requests", ["status"])

    op.create_table(
        "bids",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("provider_did", sa.String(length=255), nullable=False),
        sa.Column("price_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("signed_payload", sa.JSON(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("bid_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("price_micro_usdc <= 10000", name="ck_bids_max_price"),
        sa.ForeignKeyConstraint(["request_id"], ["service_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "provider_did", "nonce", name="uq_bids_request_provider_nonce"),
    )
    op.create_index("ix_bids_bid_hash", "bids", ["bid_hash"])
    op.create_index("ix_bids_provider_did", "bids", ["provider_did"])
    op.create_index("ix_bids_request_id", "bids", ["request_id"])
    op.create_index("ix_bids_status", "bids", ["status"])


def downgrade() -> None:
    op.drop_index("ix_bids_status", table_name="bids")
    op.drop_index("ix_bids_request_id", table_name="bids")
    op.drop_index("ix_bids_provider_did", table_name="bids")
    op.drop_index("ix_bids_bid_hash", table_name="bids")
    op.drop_table("bids")
    op.drop_index("ix_service_requests_status", table_name="service_requests")
    op.drop_index("ix_service_requests_capability", table_name="service_requests")
    op.drop_index("ix_service_requests_buyer_did", table_name="service_requests")
    op.drop_table("service_requests")
