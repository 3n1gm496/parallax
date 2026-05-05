"""shadow_candidate_observations: persisted candidate drought diagnostics

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_candidate_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("relation_key", sa.String(length=255), nullable=False),
        sa.Column("relation_kind", sa.String(length=50), nullable=False),
        sa.Column("relation_type", sa.String(length=100), nullable=False),
        sa.Column("market_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("identity_status", sa.String(length=50), nullable=False, server_default="unresolved"),
        sa.Column("identity_version", sa.String(length=100), nullable=False, server_default="identity-v1"),
        sa.Column("proof_status", sa.String(length=50), nullable=False, server_default="needs_review"),
        sa.Column("tradeable_relation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("solver_called", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("solver_skip_reason", sa.String(length=100), nullable=True),
        sa.Column("solver_none_reason", sa.String(length=100), nullable=True),
        sa.Column("displayed_edge", sa.Float(), nullable=True),
        sa.Column("executable_edge", sa.Float(), nullable=True),
        sa.Column("worst_case_payoff", sa.Float(), nullable=True),
        sa.Column("valid_state_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impossible_state_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("false_arbitrage_label", sa.String(length=100), nullable=True),
        sa.Column("min_profit_threshold", sa.Float(), nullable=False, server_default="0.005"),
        sa.Column("rejected_by_threshold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rejected_by_identity", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rejected_by_false_arbitrage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rejected_by_dedup", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("execution_evidence_missing", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("blocking_gates", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("relaxation_flags", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("minimal_relaxation", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("dangerous_relaxation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("persisted_candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["persisted_candidate_id"], ["opportunity_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shadow_candidate_observations_run_id", "shadow_candidate_observations", ["run_id"])
    op.create_index("ix_shadow_candidate_observations_relation_key", "shadow_candidate_observations", ["relation_key"])
    op.create_index("ix_shadow_candidate_observations_relation_kind", "shadow_candidate_observations", ["relation_kind"])
    op.create_index("ix_shadow_candidate_observations_relation_type", "shadow_candidate_observations", ["relation_type"])
    op.create_index("ix_shadow_candidate_observations_identity_status", "shadow_candidate_observations", ["identity_status"])
    op.create_index("ix_shadow_candidate_observations_proof_status", "shadow_candidate_observations", ["proof_status"])
    op.create_index("ix_shadow_candidate_observations_tradeable_relation", "shadow_candidate_observations", ["tradeable_relation"])
    op.create_index("ix_shadow_candidate_observations_solver_called", "shadow_candidate_observations", ["solver_called"])
    op.create_index("ix_shadow_candidate_observations_solver_skip_reason", "shadow_candidate_observations", ["solver_skip_reason"])
    op.create_index("ix_shadow_candidate_observations_solver_none_reason", "shadow_candidate_observations", ["solver_none_reason"])
    op.create_index("ix_shadow_candidate_observations_false_arbitrage_label", "shadow_candidate_observations", ["false_arbitrage_label"])
    op.create_index("ix_shadow_candidate_observations_rejected_by_threshold", "shadow_candidate_observations", ["rejected_by_threshold"])
    op.create_index("ix_shadow_candidate_observations_rejected_by_identity", "shadow_candidate_observations", ["rejected_by_identity"])
    op.create_index("ix_shadow_candidate_observations_rejected_by_false_arbitrage", "shadow_candidate_observations", ["rejected_by_false_arbitrage"])
    op.create_index("ix_shadow_candidate_observations_rejected_by_dedup", "shadow_candidate_observations", ["rejected_by_dedup"])
    op.create_index("ix_shadow_candidate_observations_execution_evidence_missing", "shadow_candidate_observations", ["execution_evidence_missing"])
    op.create_index("ix_shadow_candidate_observations_persisted_candidate_id", "shadow_candidate_observations", ["persisted_candidate_id"])
    op.create_index(
        "ix_shadow_candidate_observations_run_kind_created",
        "shadow_candidate_observations",
        ["run_id", "relation_kind", "created_at"],
    )
    op.create_index(
        "ix_shadow_candidate_observations_run_relation_key",
        "shadow_candidate_observations",
        ["run_id", "relation_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_shadow_candidate_observations_run_relation_key", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_run_kind_created", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_persisted_candidate_id", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_execution_evidence_missing", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_rejected_by_dedup", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_rejected_by_false_arbitrage", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_rejected_by_identity", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_rejected_by_threshold", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_false_arbitrage_label", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_solver_none_reason", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_solver_skip_reason", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_solver_called", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_tradeable_relation", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_proof_status", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_identity_status", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_relation_type", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_relation_kind", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_relation_key", table_name="shadow_candidate_observations")
    op.drop_index("ix_shadow_candidate_observations_run_id", table_name="shadow_candidate_observations")
    op.drop_table("shadow_candidate_observations")
