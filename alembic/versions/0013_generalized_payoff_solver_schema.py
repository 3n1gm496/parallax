"""generalized_payoff_solver_schema: solver artifacts, policies, and audit storage

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("opportunity_candidates", sa.Column("scenario_matrix_json", sa.JSON(), nullable=True))
    op.add_column("opportunity_candidates", sa.Column("proof_object_json", sa.JSON(), nullable=True))
    op.add_column("opportunity_candidates", sa.Column("solver_version", sa.String(length=100), nullable=True))
    op.add_column("opportunity_candidates", sa.Column("constraint_fingerprint", sa.String(length=255), nullable=True))
    op.add_column("opportunity_candidates", sa.Column("basket_json", sa.JSON(), nullable=True))
    op.add_column("opportunity_candidates", sa.Column("false_arbitrage_label", sa.String(length=100), nullable=True))
    op.create_index("ix_opportunity_candidates_solver_version", "opportunity_candidates", ["solver_version"])
    op.create_index(
        "ix_opportunity_candidates_constraint_fingerprint",
        "opportunity_candidates",
        ["constraint_fingerprint"],
    )
    op.create_index(
        "ix_opportunity_candidates_false_arbitrage_label",
        "opportunity_candidates",
        ["false_arbitrage_label"],
    )
    op.create_index(
        "ix_opportunity_candidates_solver_dedupe",
        "opportunity_candidates",
        ["status", "solver_version", "constraint_fingerprint"],
        unique=False,
    )

    op.create_table(
        "solver_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_key", sa.String(length=100), nullable=False),
        sa.Column("solver_version", sa.String(length=100), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_key"),
    )
    op.create_index("ix_solver_policies_policy_key", "solver_policies", ["policy_key"], unique=True)
    op.create_index("ix_solver_policies_solver_version", "solver_policies", ["solver_version"])

    op.create_table(
        "solver_fixtures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_key", sa.String(length=255), nullable=False),
        sa.Column("fixture_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_key"),
    )
    op.create_index("ix_solver_fixtures_case_key", "solver_fixtures", ["case_key"], unique=True)

    op.create_table(
        "solver_audit_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("constraint_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("solver_version", sa.String(length=100), nullable=False),
        sa.Column("policy_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="solved"),
        sa.Column("audit_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["opportunity_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_solver_audit_records_candidate_id", "solver_audit_records", ["candidate_id"])
    op.create_index(
        "ix_solver_audit_records_fingerprint_solver",
        "solver_audit_records",
        ["constraint_fingerprint", "solver_version", "created_at"],
    )
    op.create_index("ix_solver_audit_records_policy_key", "solver_audit_records", ["policy_key"])
    op.create_index("ix_solver_audit_records_solver_version", "solver_audit_records", ["solver_version"])
    op.create_index("ix_solver_audit_records_status", "solver_audit_records", ["status"])


def downgrade() -> None:
    op.drop_index("ix_solver_audit_records_status", table_name="solver_audit_records")
    op.drop_index("ix_solver_audit_records_solver_version", table_name="solver_audit_records")
    op.drop_index("ix_solver_audit_records_policy_key", table_name="solver_audit_records")
    op.drop_index("ix_solver_audit_records_fingerprint_solver", table_name="solver_audit_records")
    op.drop_index("ix_solver_audit_records_candidate_id", table_name="solver_audit_records")
    op.drop_table("solver_audit_records")

    op.drop_index("ix_solver_fixtures_case_key", table_name="solver_fixtures")
    op.drop_table("solver_fixtures")

    op.drop_index("ix_solver_policies_solver_version", table_name="solver_policies")
    op.drop_index("ix_solver_policies_policy_key", table_name="solver_policies")
    op.drop_table("solver_policies")

    op.drop_index("ix_opportunity_candidates_solver_dedupe", table_name="opportunity_candidates")
    op.drop_index("ix_opportunity_candidates_false_arbitrage_label", table_name="opportunity_candidates")
    op.drop_index("ix_opportunity_candidates_constraint_fingerprint", table_name="opportunity_candidates")
    op.drop_index("ix_opportunity_candidates_solver_version", table_name="opportunity_candidates")
    op.drop_column("opportunity_candidates", "false_arbitrage_label")
    op.drop_column("opportunity_candidates", "basket_json")
    op.drop_column("opportunity_candidates", "constraint_fingerprint")
    op.drop_column("opportunity_candidates", "solver_version")
    op.drop_column("opportunity_candidates", "proof_object_json")
    op.drop_column("opportunity_candidates", "scenario_matrix_json")
