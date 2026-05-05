"""decision ledger records

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_ledger_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("source_of_truth", sa.String(length=50), nullable=False),
        sa.Column("fallback_status", sa.String(length=50), nullable=False, server_default="none"),
        sa.Column("model_version", sa.String(length=100), nullable=False, server_default="decision-ledger-v1"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("input_packet", sa.JSON(), nullable=True),
        sa.Column("relation_proof", sa.JSON(), nullable=True),
        sa.Column("execution_evidence", sa.JSON(), nullable=True),
        sa.Column("blocking_reason", sa.Text(), nullable=True),
        sa.Column("counterexamples", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["opportunity_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_decision_ledger_records_candidate_evaluated",
        "decision_ledger_records",
        ["candidate_id", "evaluated_at"],
        unique=False,
    )
    op.create_index(
        "ix_decision_ledger_records_run_evaluated",
        "decision_ledger_records",
        ["run_id", "evaluated_at"],
        unique=False,
    )
    op.create_index("ix_decision_ledger_records_candidate_id", "decision_ledger_records", ["candidate_id"], unique=False)
    op.create_index("ix_decision_ledger_records_run_id", "decision_ledger_records", ["run_id"], unique=False)
    op.create_index("ix_decision_ledger_records_created_at", "decision_ledger_records", ["created_at"], unique=False)
    op.create_index("ix_decision_ledger_records_decision", "decision_ledger_records", ["decision"], unique=False)
    op.create_index("ix_decision_ledger_records_source_of_truth", "decision_ledger_records", ["source_of_truth"], unique=False)
    op.create_index("ix_decision_ledger_records_fallback_status", "decision_ledger_records", ["fallback_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_decision_ledger_records_fallback_status", table_name="decision_ledger_records")
    op.drop_index("ix_decision_ledger_records_source_of_truth", table_name="decision_ledger_records")
    op.drop_index("ix_decision_ledger_records_decision", table_name="decision_ledger_records")
    op.drop_index("ix_decision_ledger_records_created_at", table_name="decision_ledger_records")
    op.drop_index("ix_decision_ledger_records_run_id", table_name="decision_ledger_records")
    op.drop_index("ix_decision_ledger_records_candidate_id", table_name="decision_ledger_records")
    op.drop_index("ix_decision_ledger_records_run_evaluated", table_name="decision_ledger_records")
    op.drop_index("ix_decision_ledger_records_candidate_evaluated", table_name="decision_ledger_records")
    op.drop_table("decision_ledger_records")
