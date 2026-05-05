"""trade_certificates_and_calibration: certificate gating and closed-loop policy

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_positions", sa.Column("certificate_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_paper_positions_certificate_id", "paper_positions", ["certificate_id"])

    op.create_table(
        "trade_proof_certificates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("certificate_version", sa.String(length=100), nullable=False),
        sa.Column("certificate_status", sa.String(length=50), nullable=False),
        sa.Column("market_data_snapshot_hash", sa.String(length=255), nullable=True),
        sa.Column("compiled_contract_versions", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("identity_evidence_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("identity_status", sa.String(length=50), nullable=False),
        sa.Column("identity_confidence", sa.Float(), nullable=True),
        sa.Column("identity_provenance", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("identity_cluster_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("relation_proof_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("relation_set_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("solver_proof_object_hash", sa.String(length=255), nullable=False),
        sa.Column("payoff_matrix_hash", sa.String(length=255), nullable=False),
        sa.Column("scenario_matrix_hash", sa.String(length=255), nullable=False),
        sa.Column("orderbook_snapshot_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("execution_model", sa.String(length=50), nullable=False),
        sa.Column("execution_simulation_hash", sa.String(length=255), nullable=True),
        sa.Column("court_decision_snapshot_id", sa.String(length=255), nullable=True),
        sa.Column("risk_score_version", sa.String(length=100), nullable=True),
        sa.Column("policy_version", sa.String(length=100), nullable=True),
        sa.Column("config_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("provider_fingerprints", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("invalidation_conditions", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("invalidation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_certificate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["candidate_id"], ["opportunity_candidates.id"]),
        sa.ForeignKeyConstraint(["supersedes_certificate_id"], ["trade_proof_certificates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trade_proof_certificates_candidate_id", "trade_proof_certificates", ["candidate_id"])
    op.create_index("ix_trade_proof_certificates_run_id", "trade_proof_certificates", ["run_id"])
    op.create_index("ix_trade_proof_certificates_certificate_status", "trade_proof_certificates", ["certificate_status"])
    op.create_index("ix_trade_proof_certificates_solver_proof_object_hash", "trade_proof_certificates", ["solver_proof_object_hash"])
    op.create_index(
        "ix_trade_proof_certificates_candidate_status_generated",
        "trade_proof_certificates",
        ["candidate_id", "certificate_status", "generated_at"],
    )
    op.create_index("ix_trade_proof_certificates_supersedes_certificate_id", "trade_proof_certificates", ["supersedes_certificate_id"])

    op.create_table(
        "calibration_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("input_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_policy_version", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calibration_runs_status", "calibration_runs", ["status"])
    op.create_index("ix_calibration_runs_created_at", "calibration_runs", ["created_at"])

    op.create_table(
        "active_policy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("court_thresholds", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("risk_weights", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("solver_penalties", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("execution_calibration", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_version"),
    )
    op.create_index("ix_active_policy_versions_policy_version", "active_policy_versions", ["policy_version"], unique=True)
    op.create_index("ix_active_policy_versions_status", "active_policy_versions", ["status"])
    op.create_index("ix_active_policy_versions_created_at", "active_policy_versions", ["created_at"])

    op.create_table(
        "opportunity_type_scorecards",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("calibration_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opportunity_type", sa.String(length=100), nullable=False),
        sa.Column("scorecard_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["calibration_run_id"], ["calibration_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_opportunity_type_scorecards_calibration_run_id", "opportunity_type_scorecards", ["calibration_run_id"])
    op.create_index("ix_opportunity_type_scorecards_opportunity_type", "opportunity_type_scorecards", ["opportunity_type"])

    op.create_table(
        "strategy_kill_list",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_key", sa.String(length=150), nullable=False),
        sa.Column("warning_level", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_key"),
    )
    op.create_index("ix_strategy_kill_list_strategy_key", "strategy_kill_list", ["strategy_key"], unique=True)
    op.create_index("ix_strategy_kill_list_warning_level", "strategy_kill_list", ["warning_level"])
    op.create_index("ix_strategy_kill_list_active", "strategy_kill_list", ["active"])

    for table_name in ("identity_feedback_events", "solver_feedback_events", "execution_feedback_events", "oracle_feedback_events"):
        op.create_table(
            table_name,
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("calibration_run_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("feedback_type", sa.String(length=100), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["calibration_run_id"], ["calibration_runs.id"]),
            sa.ForeignKeyConstraint(["candidate_id"], ["opportunity_candidates.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(f"ix_{table_name}_calibration_run_id", table_name, ["calibration_run_id"])
        op.create_index(f"ix_{table_name}_candidate_id", table_name, ["candidate_id"])
        op.create_index(f"ix_{table_name}_feedback_type", table_name, ["feedback_type"])


def downgrade() -> None:
    for table_name in ("oracle_feedback_events", "execution_feedback_events", "solver_feedback_events", "identity_feedback_events"):
        op.drop_index(f"ix_{table_name}_feedback_type", table_name=table_name)
        op.drop_index(f"ix_{table_name}_candidate_id", table_name=table_name)
        op.drop_index(f"ix_{table_name}_calibration_run_id", table_name=table_name)
        op.drop_table(table_name)

    op.drop_index("ix_strategy_kill_list_active", table_name="strategy_kill_list")
    op.drop_index("ix_strategy_kill_list_warning_level", table_name="strategy_kill_list")
    op.drop_index("ix_strategy_kill_list_strategy_key", table_name="strategy_kill_list")
    op.drop_table("strategy_kill_list")

    op.drop_index("ix_opportunity_type_scorecards_opportunity_type", table_name="opportunity_type_scorecards")
    op.drop_index("ix_opportunity_type_scorecards_calibration_run_id", table_name="opportunity_type_scorecards")
    op.drop_table("opportunity_type_scorecards")

    op.drop_index("ix_active_policy_versions_created_at", table_name="active_policy_versions")
    op.drop_index("ix_active_policy_versions_status", table_name="active_policy_versions")
    op.drop_index("ix_active_policy_versions_policy_version", table_name="active_policy_versions")
    op.drop_table("active_policy_versions")

    op.drop_index("ix_calibration_runs_created_at", table_name="calibration_runs")
    op.drop_index("ix_calibration_runs_status", table_name="calibration_runs")
    op.drop_table("calibration_runs")

    op.drop_index("ix_trade_proof_certificates_supersedes_certificate_id", table_name="trade_proof_certificates")
    op.drop_index("ix_trade_proof_certificates_candidate_status_generated", table_name="trade_proof_certificates")
    op.drop_index("ix_trade_proof_certificates_solver_proof_object_hash", table_name="trade_proof_certificates")
    op.drop_index("ix_trade_proof_certificates_certificate_status", table_name="trade_proof_certificates")
    op.drop_index("ix_trade_proof_certificates_run_id", table_name="trade_proof_certificates")
    op.drop_index("ix_trade_proof_certificates_candidate_id", table_name="trade_proof_certificates")
    op.drop_table("trade_proof_certificates")

    op.drop_index("ix_paper_positions_certificate_id", table_name="paper_positions")
    op.drop_column("paper_positions", "certificate_id")
