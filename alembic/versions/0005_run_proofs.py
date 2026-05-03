"""run proof persistence

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-02
"""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_proofs",
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("run_status", sa.String(length=50), nullable=False, server_default="completed"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("provider_fingerprints", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("readiness_checks", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("control_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("markets_ingested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("market_counts_by_platform", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("contracts_compiled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("events_resolved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relations_detected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_watchlisted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("positions_opened", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("positions_settled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fatal_errors", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("non_fatal_errors", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("proof_version", sa.String(length=100), nullable=False, server_default="run-proof-v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_run_proofs_run_status", "run_proofs", ["run_status"], unique=False)
    op.create_index("ix_run_proofs_started_at", "run_proofs", ["started_at"], unique=False)
    op.create_index(
        "ix_run_proofs_config_fingerprint", "run_proofs", ["config_fingerprint"], unique=False
    )
    op.create_index(
        "ix_run_proofs_status_completed",
        "run_proofs",
        ["run_status", "completed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_run_proofs_status_completed", table_name="run_proofs")
    op.drop_index("ix_run_proofs_config_fingerprint", table_name="run_proofs")
    op.drop_index("ix_run_proofs_started_at", table_name="run_proofs")
    op.drop_index("ix_run_proofs_run_status", table_name="run_proofs")
    op.drop_table("run_proofs")
