"""identity match reviews for scored identity persistence

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_match_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_market_id", sa.String(length=255), nullable=False),
        sa.Column("canonical_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="unresolved"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("scorer_version", sa.String(length=100), nullable=False, server_default="identity-v2"),
        sa.Column("review_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["canonical_event_id"], ["canonical_events.id"]),
        sa.ForeignKeyConstraint(["raw_market_id"], ["raw_markets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_market_id"),
    )
    op.create_index(
        "ix_identity_match_reviews_raw_market_id",
        "identity_match_reviews",
        ["raw_market_id"],
        unique=True,
    )
    op.create_index(
        "ix_identity_match_reviews_canonical_event_id",
        "identity_match_reviews",
        ["canonical_event_id"],
        unique=False,
    )
    op.create_index(
        "ix_identity_match_reviews_status",
        "identity_match_reviews",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_identity_match_reviews_reviewed_at",
        "identity_match_reviews",
        ["reviewed_at"],
        unique=False,
    )
    op.create_index(
        "ix_identity_match_reviews_status_reviewed",
        "identity_match_reviews",
        ["status", "reviewed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_identity_match_reviews_status_reviewed", table_name="identity_match_reviews")
    op.drop_index("ix_identity_match_reviews_reviewed_at", table_name="identity_match_reviews")
    op.drop_index("ix_identity_match_reviews_status", table_name="identity_match_reviews")
    op.drop_index("ix_identity_match_reviews_canonical_event_id", table_name="identity_match_reviews")
    op.drop_index("ix_identity_match_reviews_raw_market_id", table_name="identity_match_reviews")
    op.drop_table("identity_match_reviews")
