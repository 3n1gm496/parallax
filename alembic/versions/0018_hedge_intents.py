"""hedge intents

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hedge_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("legs_to_unwind", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["opportunity_candidates.id"]),
        sa.ForeignKeyConstraint(["position_id"], ["paper_positions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hedge_intents_candidate_id", "hedge_intents", ["candidate_id"], unique=False)
    op.create_index("ix_hedge_intents_position_id", "hedge_intents", ["position_id"], unique=False)
    op.create_index("ix_hedge_intents_status", "hedge_intents", ["status"], unique=False)
    op.create_index("ix_hedge_intents_created_at", "hedge_intents", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_hedge_intents_created_at", table_name="hedge_intents")
    op.drop_index("ix_hedge_intents_status", table_name="hedge_intents")
    op.drop_index("ix_hedge_intents_position_id", table_name="hedge_intents")
    op.drop_index("ix_hedge_intents_candidate_id", table_name="hedge_intents")
    op.drop_table("hedge_intents")
