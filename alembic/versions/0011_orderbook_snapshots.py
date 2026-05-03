"""orderbook_snapshots: execution reality layer snapshot storage

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orderbook_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("raw_market_id", sa.String(length=255), nullable=False),
        sa.Column("token_id", sa.String(length=512), nullable=True),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bid_levels", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("ask_levels", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("mid_price", sa.Float(), nullable=True),
        sa.Column("spread_bps", sa.Float(), nullable=True),
        sa.Column("total_bid_depth", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_ask_depth", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("fetcher_version", sa.String(length=50), nullable=False, server_default="snapshot-v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orderbook_snapshots_platform", "orderbook_snapshots", ["platform"])
    op.create_index(
        "ix_orderbook_snapshots_market_captured",
        "orderbook_snapshots",
        ["raw_market_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_orderbook_snapshots_market_captured", table_name="orderbook_snapshots")
    op.drop_index("ix_orderbook_snapshots_platform", table_name="orderbook_snapshots")
    op.drop_table("orderbook_snapshots")
