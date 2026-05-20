"""Marketplace listings (Sprint 10 / Etsy-for-AI direction)

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        # Seller
        sa.Column("seller_kind", sa.String(32), nullable=False),
        sa.Column("seller_did", sa.String(255), nullable=False),
        sa.Column("payout_wallet", sa.String(64), nullable=False),
        # Kind
        sa.Column("listing_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(64), nullable=False, server_default="other"),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        # Pricing
        sa.Column("price_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("price_currency", sa.String(8), nullable=False, server_default="USDC"),
        # Service-specific
        sa.Column("service_capability", sa.String(64), nullable=True),
        sa.Column("service_input_schema", sa.JSON(), nullable=True),
        # Digital-product specific
        sa.Column("digital_content_type", sa.String(64), nullable=True),
        sa.Column("digital_content", sa.JSON(), nullable=True),
        # Presentation
        sa.Column("cover_image_url", sa.Text(), nullable=True),
        sa.Column("images", sa.JSON(), nullable=False, server_default="[]"),
        # State
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        # Stats
        sa.Column("sales_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rating_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_listings_seller_did", "listings", ["seller_did"])
    op.create_index("ix_listings_seller_kind", "listings", ["seller_kind"])
    op.create_index("ix_listings_listing_type", "listings", ["listing_type"])
    op.create_index("ix_listings_category", "listings", ["category"])
    op.create_index("ix_listings_status", "listings", ["status"])


def downgrade() -> None:
    op.drop_index("ix_listings_status", table_name="listings")
    op.drop_index("ix_listings_category", table_name="listings")
    op.drop_index("ix_listings_listing_type", table_name="listings")
    op.drop_index("ix_listings_seller_kind", table_name="listings")
    op.drop_index("ix_listings_seller_did", table_name="listings")
    op.drop_table("listings")
