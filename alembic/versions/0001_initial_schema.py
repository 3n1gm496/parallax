"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False, index=True),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )

    op.create_table(
        "raw_markets",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("platform", sa.String(50), nullable=False, index=True),
        sa.Column("market_id", sa.String(255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("resolution_criteria", sa.Text(), nullable=False),
        sa.Column("outcomes", sa.JSON(), nullable=False),
        sa.Column("outcome_prices", sa.JSON(), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("group_id", sa.String(255), nullable=True, index=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("is_closed", sa.Boolean(), nullable=False, default=False),
        sa.Column("resolution_source", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "compiled_contracts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("raw_market_id", sa.String(255), sa.ForeignKey("raw_markets.id"), nullable=False, index=True),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column("compiler_confidence", sa.Float(), nullable=False),
        sa.Column("compiler_version", sa.String(100), nullable=False),
        sa.Column("compiled_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "canonical_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(100), nullable=False, index=True),
        sa.Column("platform_group_key", sa.String(255), nullable=True, unique=True),
        sa.Column("status", sa.String(50), nullable=False, default="active"),
        sa.Column("resolution", sa.String(100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "market_event_links",
        sa.Column("raw_market_id", sa.String(255), sa.ForeignKey("raw_markets.id"), primary_key=True),
        sa.Column("canonical_event_id", UUID(as_uuid=True), sa.ForeignKey("canonical_events.id"), primary_key=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "market_relations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("from_market_id", sa.String(255), nullable=False, index=True),
        sa.Column("to_market_id", sa.String(255), nullable=False, index=True),
        sa.Column("relation_type", sa.String(100), nullable=False, index=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_market_relations_pair", "market_relations", ["from_market_id", "to_market_id"])

    op.create_table(
        "opportunity_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("market_ids", sa.JSON(), nullable=False),
        sa.Column("payoff_matrix", sa.JSON(), nullable=False),
        sa.Column("opportunity_type", sa.String(100), nullable=False, index=True),
        sa.Column("worst_case_payoff", sa.Float(), nullable=False),
        sa.Column("friction_bps", sa.Integer(), nullable=False),
        sa.Column("risk_scores", sa.JSON(), nullable=False),
        sa.Column("court_decision", sa.String(50), nullable=False, default="PENDING"),
        sa.Column("status", sa.String(50), nullable=False, default="open", index=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "paper_positions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("candidate_id", UUID(as_uuid=True), sa.ForeignKey("opportunity_candidates.id"), nullable=False, index=True),
        sa.Column("status", sa.String(50), nullable=False, default="OPEN"),
        sa.Column("legs_json", sa.JSON(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_pnl", sa.Float(), nullable=True),
    )

    op.create_table(
        "autopsy_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("candidate_id", UUID(as_uuid=True), sa.ForeignKey("opportunity_candidates.id"), nullable=False, index=True),
        sa.Column("position_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actual_resolution", sa.JSON(), nullable=False),
        sa.Column("resolution_type", sa.String(100), nullable=False, index=True),
        sa.Column("identity_error", sa.Boolean(), nullable=False, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("autopsy_records")
    op.drop_table("paper_positions")
    op.drop_table("opportunity_candidates")
    op.drop_index("ix_market_relations_pair", table_name="market_relations")
    op.drop_table("market_relations")
    op.drop_table("market_event_links")
    op.drop_table("canonical_events")
    op.drop_table("compiled_contracts")
    op.drop_table("raw_markets")
    op.drop_table("audit_events")
