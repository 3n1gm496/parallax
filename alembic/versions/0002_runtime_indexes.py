"""runtime indexes for operational queries

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-02
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_events_entity_lookup",
        "audit_events",
        ["entity_type", "entity_id", "created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_raw_markets_platform_group_deadline",
        "raw_markets",
        ["platform", "group_id", "deadline"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_raw_markets_platform_updated_at",
        "raw_markets",
        ["platform", "updated_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_canonical_events_domain_status",
        "canonical_events",
        ["domain", "status"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_market_event_links_event",
        "market_event_links",
        ["canonical_event_id", "linked_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_opportunity_candidates_status_decision_detected",
        "opportunity_candidates",
        ["status", "court_decision", "detected_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_paper_positions_candidate_status_opened",
        "paper_positions",
        ["candidate_id", "status", "opened_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_autopsy_records_candidate_created",
        "autopsy_records",
        ["candidate_id", "created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_autopsy_records_identity_error_created",
        "autopsy_records",
        ["identity_error", "created_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_autopsy_records_identity_error_created", table_name="autopsy_records", if_exists=True)
    op.drop_index("ix_autopsy_records_candidate_created", table_name="autopsy_records", if_exists=True)
    op.drop_index("ix_paper_positions_candidate_status_opened", table_name="paper_positions", if_exists=True)
    op.drop_index(
        "ix_opportunity_candidates_status_decision_detected",
        table_name="opportunity_candidates",
        if_exists=True,
    )
    op.drop_index("ix_market_event_links_event", table_name="market_event_links", if_exists=True)
    op.drop_index("ix_canonical_events_domain_status", table_name="canonical_events", if_exists=True)
    op.drop_index("ix_raw_markets_platform_updated_at", table_name="raw_markets", if_exists=True)
    op.drop_index("ix_raw_markets_platform_group_deadline", table_name="raw_markets", if_exists=True)
    op.drop_index("ix_audit_events_entity_lookup", table_name="audit_events", if_exists=True)
