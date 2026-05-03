"""counterexample records and relation quality storage

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counterexample_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("set_key", sa.String(length=255), nullable=True),
        sa.Column("relation_type", sa.String(length=100), nullable=False),
        sa.Column("scenario_description", sa.Text(), nullable=False),
        sa.Column("resolution_a", sa.String(length=20), nullable=False),
        sa.Column("resolution_b", sa.String(length=20), nullable=False),
        sa.Column("why_different", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="recorded"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["relation_id"], ["logical_relations.id"]),
        sa.ForeignKeyConstraint(["review_id"], ["relation_reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_counterexample_records_relation_id", "counterexample_records", ["relation_id"], unique=False)
    op.create_index("ix_counterexample_records_review_id", "counterexample_records", ["review_id"], unique=False)
    op.create_index("ix_counterexample_records_set_key", "counterexample_records", ["set_key"], unique=False)
    op.create_index("ix_counterexample_records_relation_type", "counterexample_records", ["relation_type"], unique=False)
    op.create_index("ix_counterexample_records_source", "counterexample_records", ["source"], unique=False)
    op.create_index("ix_counterexample_records_status", "counterexample_records", ["status"], unique=False)
    op.create_index(
        "ix_counterexample_records_relation_status",
        "counterexample_records",
        ["relation_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_counterexample_records_review_status",
        "counterexample_records",
        ["review_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_counterexample_records_review_status", table_name="counterexample_records")
    op.drop_index("ix_counterexample_records_relation_status", table_name="counterexample_records")
    op.drop_index("ix_counterexample_records_status", table_name="counterexample_records")
    op.drop_index("ix_counterexample_records_source", table_name="counterexample_records")
    op.drop_index("ix_counterexample_records_relation_type", table_name="counterexample_records")
    op.drop_index("ix_counterexample_records_set_key", table_name="counterexample_records")
    op.drop_index("ix_counterexample_records_review_id", table_name="counterexample_records")
    op.drop_index("ix_counterexample_records_relation_id", table_name="counterexample_records")
    op.drop_table("counterexample_records")
