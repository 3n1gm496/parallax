"""relation layer v2 storage

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compiled_propositions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_market_id", sa.String(length=255), nullable=False),
        sa.Column("proposition_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("compiler_version", sa.String(length=100), nullable=False),
        sa.Column("compiled_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["raw_market_id"], ["raw_markets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_market_id"),
    )
    op.create_index("ix_compiled_propositions_raw_market_id", "compiled_propositions", ["raw_market_id"], unique=True)

    op.create_table(
        "canonical_event_frames",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("frame_key", sa.String(length=255), nullable=False),
        sa.Column("frame_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(length=100), nullable=False),
        sa.Column("canonical_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["canonical_event_id"], ["canonical_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("frame_key"),
    )
    op.create_index("ix_canonical_event_frames_frame_key", "canonical_event_frames", ["frame_key"], unique=True)
    op.create_index("ix_canonical_event_frames_canonical_event_id", "canonical_event_frames", ["canonical_event_id"], unique=False)
    op.create_index("ix_canonical_event_frames_domain_type", "canonical_event_frames", ["domain", "frame_type"], unique=False)

    op.create_table(
        "event_frame_memberships",
        sa.Column("raw_market_id", sa.String(length=255), nullable=False),
        sa.Column("frame_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_type", sa.String(length=100), nullable=False, server_default="same_event_family"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["frame_id"], ["canonical_event_frames.id"]),
        sa.ForeignKeyConstraint(["raw_market_id"], ["raw_markets.id"]),
        sa.PrimaryKeyConstraint("raw_market_id", "frame_id"),
    )
    op.create_index("ix_event_frame_memberships_frame", "event_frame_memberships", ["frame_id", "created_at"], unique=False)

    op.create_table(
        "logical_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_market_id", sa.String(length=255), nullable=False),
        sa.Column("to_market_id", sa.String(length=255), nullable=False),
        sa.Column("frame_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("relation_type", sa.String(length=100), nullable=False),
        sa.Column("proof_status", sa.String(length=50), nullable=False, server_default="verified"),
        sa.Column("tradeable_relation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["frame_id"], ["canonical_event_frames.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_logical_relations_pair", "logical_relations", ["from_market_id", "to_market_id"], unique=False)
    op.create_index("ix_logical_relations_tradeable", "logical_relations", ["tradeable_relation", "proof_status"], unique=False)
    op.create_index("ix_logical_relations_frame_id", "logical_relations", ["frame_id"], unique=False)

    op.create_table(
        "relation_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_market_id", sa.String(length=255), nullable=False),
        sa.Column("to_market_id", sa.String(length=255), nullable=False),
        sa.Column("proposed_relation_type", sa.String(length=100), nullable=False),
        sa.Column("reviewed_relation_type", sa.String(length=100), nullable=True),
        sa.Column("proof_status", sa.String(length=50), nullable=False, server_default="needs_review"),
        sa.Column("tradeable_relation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("review_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("reviewed_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_relation_reviews_from_market_id", "relation_reviews", ["from_market_id"], unique=False)
    op.create_index("ix_relation_reviews_to_market_id", "relation_reviews", ["to_market_id"], unique=False)
    op.create_index("ix_relation_reviews_proposed_relation_type", "relation_reviews", ["proposed_relation_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_relation_reviews_proposed_relation_type", table_name="relation_reviews")
    op.drop_index("ix_relation_reviews_to_market_id", table_name="relation_reviews")
    op.drop_index("ix_relation_reviews_from_market_id", table_name="relation_reviews")
    op.drop_table("relation_reviews")
    op.drop_index("ix_logical_relations_frame_id", table_name="logical_relations")
    op.drop_index("ix_logical_relations_tradeable", table_name="logical_relations")
    op.drop_index("ix_logical_relations_pair", table_name="logical_relations")
    op.drop_table("logical_relations")
    op.drop_index("ix_event_frame_memberships_frame", table_name="event_frame_memberships")
    op.drop_table("event_frame_memberships")
    op.drop_index("ix_canonical_event_frames_domain_type", table_name="canonical_event_frames")
    op.drop_index("ix_canonical_event_frames_canonical_event_id", table_name="canonical_event_frames")
    op.drop_index("ix_canonical_event_frames_frame_key", table_name="canonical_event_frames")
    op.drop_table("canonical_event_frames")
    op.drop_index("ix_compiled_propositions_raw_market_id", table_name="compiled_propositions")
    op.drop_table("compiled_propositions")
