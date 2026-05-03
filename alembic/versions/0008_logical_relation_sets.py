"""logical relation sets for n-ary proof storage

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "logical_relation_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("set_key", sa.String(length=255), nullable=False),
        sa.Column("frame_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("member_market_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("relation_type", sa.String(length=100), nullable=False),
        sa.Column("proof_status", sa.String(length=50), nullable=False, server_default="verified"),
        sa.Column("tradeable_relation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["frame_id"], ["canonical_event_frames.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("set_key"),
    )
    op.create_index("ix_logical_relation_sets_set_key", "logical_relation_sets", ["set_key"], unique=True)
    op.create_index("ix_logical_relation_sets_frame_id", "logical_relation_sets", ["frame_id"], unique=False)
    op.create_index(
        "ix_logical_relation_sets_tradeable",
        "logical_relation_sets",
        ["tradeable_relation", "proof_status"],
        unique=False,
    )
    op.create_index(
        "ix_logical_relation_sets_frame_relation",
        "logical_relation_sets",
        ["frame_id", "relation_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_logical_relation_sets_frame_relation", table_name="logical_relation_sets")
    op.drop_index("ix_logical_relation_sets_tradeable", table_name="logical_relation_sets")
    op.drop_index("ix_logical_relation_sets_frame_id", table_name="logical_relation_sets")
    op.drop_index("ix_logical_relation_sets_set_key", table_name="logical_relation_sets")
    op.drop_table("logical_relation_sets")
