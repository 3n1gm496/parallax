"""venue_tokens: platform/market/outcome to token_id mapping

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "venue_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("raw_market_id", sa.String(length=255), nullable=False),
        sa.Column("token_id", sa.String(length=512), nullable=False),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "raw_market_id", "outcome", name="uq_venue_tokens_platform_market_outcome"),
    )
    op.create_index("ix_venue_tokens_platform", "venue_tokens", ["platform"])
    op.create_index("ix_venue_tokens_raw_market_id", "venue_tokens", ["raw_market_id"])
    op.create_index("ix_venue_tokens_token_id", "venue_tokens", ["token_id"])


def downgrade() -> None:
    op.drop_index("ix_venue_tokens_token_id", table_name="venue_tokens")
    op.drop_index("ix_venue_tokens_raw_market_id", table_name="venue_tokens")
    op.drop_index("ix_venue_tokens_platform", table_name="venue_tokens")
    op.drop_table("venue_tokens")
