"""candidate decision snapshots

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_decision_snapshots",
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=True),
        sa.Column("risk_score", sa.JSON(), nullable=True),
        sa.Column("relation_evidence", sa.JSON(), nullable=True),
        sa.Column("simulation_result", sa.JSON(), nullable=True),
        sa.Column("court_assessment", sa.JSON(), nullable=True),
        sa.Column("snapshot_version", sa.String(length=100), nullable=False, server_default="decision-snapshot-v1"),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["opportunity_candidates.id"]),
        sa.PrimaryKeyConstraint("candidate_id"),
    )
    op.create_index(
        "ix_candidate_decision_snapshots_run_id",
        "candidate_decision_snapshots",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_decision_snapshots_evaluated_at",
        "candidate_decision_snapshots",
        ["evaluated_at"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_decision_snapshots_run_evaluated",
        "candidate_decision_snapshots",
        ["run_id", "evaluated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_decision_snapshots_run_evaluated", table_name="candidate_decision_snapshots")
    op.drop_index("ix_candidate_decision_snapshots_evaluated_at", table_name="candidate_decision_snapshots")
    op.drop_index("ix_candidate_decision_snapshots_run_id", table_name="candidate_decision_snapshots")
    op.drop_table("candidate_decision_snapshots")
