"""identity_v3_schema: canonical entities, cluster tables, benchmark, metrics

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False, server_default="unknown"),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name"),
    )
    op.create_index("ix_canonical_entities_normalized_name", "canonical_entities", ["normalized_name"], unique=True)
    op.create_index("ix_canonical_entities_entity_type", "canonical_entities", ["entity_type"])

    op.create_table(
        "canonical_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("source_type", sa.String(length=100), nullable=False, server_default="unknown"),
        sa.Column("trust_level", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name"),
    )
    op.create_index("ix_canonical_sources_normalized_name", "canonical_sources", ["normalized_name"], unique=True)
    op.create_index("ix_canonical_sources_source_type", "canonical_sources", ["source_type"])

    op.create_table(
        "canonical_deadlines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bucket_key", sa.String(length=100), nullable=False),
        sa.Column("resolution_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_type", sa.String(length=50), nullable=False, server_default="exact"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bucket_key"),
    )
    op.create_index("ix_canonical_deadlines_bucket_key", "canonical_deadlines", ["bucket_key"], unique=True)

    op.create_table(
        "event_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_key", sa.String(length=255), nullable=False),
        sa.Column("predicate_template", sa.Text(), nullable=False),
        sa.Column("canonical_predicate", sa.String(length=100), nullable=False),
        sa.Column("example_titles", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("family_key"),
    )
    op.create_index("ix_event_templates_family_key", "event_templates", ["family_key"], unique=True)
    op.create_index("ix_event_templates_canonical_predicate", "event_templates", ["canonical_predicate"])

    op.create_table(
        "event_identity_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cluster_key", sa.String(length=500), nullable=False),
        sa.Column("identity_type", sa.String(length=100), nullable=False),
        sa.Column("primary_canonical_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("confidence_version", sa.String(length=100), nullable=False, server_default="identity-v3"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("provenance", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["primary_canonical_event_id"], ["canonical_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_key"),
    )
    op.create_index("ix_event_identity_clusters_cluster_key", "event_identity_clusters", ["cluster_key"], unique=True)
    op.create_index("ix_event_identity_clusters_identity_type", "event_identity_clusters", ["identity_type"])
    op.create_index("ix_event_identity_clusters_status", "event_identity_clusters", ["status"])
    op.create_index("ix_event_identity_clusters_type_status", "event_identity_clusters", ["identity_type", "status"])
    op.create_index("ix_event_identity_clusters_primary_event", "event_identity_clusters", ["primary_canonical_event_id"])

    op.create_table(
        "identity_cluster_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_market_id", sa.String(length=255), nullable=True),
        sa.Column("member_role", sa.String(length=50), nullable=False, server_default="secondary"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("added_by", sa.String(length=100), nullable=False, server_default="system"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.ForeignKeyConstraint(["canonical_event_id"], ["canonical_events.id"]),
        sa.ForeignKeyConstraint(["cluster_id"], ["event_identity_clusters.id"]),
        sa.ForeignKeyConstraint(["raw_market_id"], ["raw_markets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_id", "raw_market_id", name="uq_cluster_member"),
    )
    op.create_index("ix_identity_cluster_members_cluster", "identity_cluster_members", ["cluster_id", "added_at"])
    op.create_index("ix_identity_cluster_members_event", "identity_cluster_members", ["canonical_event_id"])
    op.create_index("ix_identity_cluster_members_market", "identity_cluster_members", ["raw_market_id"])

    op.create_table(
        "identity_split_merge_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("source_cluster_ids", sa.JSON(), nullable=False),
        sa.Column("target_cluster_ids", sa.JSON(), nullable=False),
        sa.Column("triggered_by", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_identity_split_merge_history_action", "identity_split_merge_history", ["action"])
    op.create_index("ix_identity_split_merge_history_acted_at", "identity_split_merge_history", ["acted_at"])

    op.create_table(
        "identity_review_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["event_identity_clusters.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_identity_review_actions_cluster_id", "identity_review_actions", ["cluster_id"])
    op.create_index("ix_identity_review_actions_action", "identity_review_actions", ["action"])
    op.create_index("ix_identity_review_actions_acted_at", "identity_review_actions", ["acted_at"])

    op.create_table(
        "identity_training_examples",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_id_a", sa.String(length=255), nullable=False),
        sa.Column("market_id_b", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("identity_type", sa.String(length=100), nullable=True),
        sa.Column("labeler", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_id_a"], ["raw_markets.id"]),
        sa.ForeignKeyConstraint(["market_id_b"], ["raw_markets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("market_id_a", "market_id_b", name="uq_training_example_pair"),
    )
    op.create_index("ix_identity_training_examples_market_a", "identity_training_examples", ["market_id_a"])
    op.create_index("ix_identity_training_examples_market_b", "identity_training_examples", ["market_id_b"])

    op.create_table(
        "identity_benchmark_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_key", sa.String(length=255), nullable=False),
        sa.Column("market_id_a", sa.String(length=255), nullable=False),
        sa.Column("market_id_b", sa.String(length=255), nullable=False),
        sa.Column("expected_label", sa.String(length=50), nullable=False),
        sa.Column("expected_identity_type", sa.String(length=100), nullable=False),
        sa.Column("difficulty", sa.String(length=50), nullable=False, server_default="medium"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_id_a"], ["raw_markets.id"]),
        sa.ForeignKeyConstraint(["market_id_b"], ["raw_markets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_key"),
    )
    op.create_index("ix_identity_benchmark_cases_case_key", "identity_benchmark_cases", ["case_key"], unique=True)

    op.create_table(
        "identity_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scorer_version", sa.String(length=100), nullable=False),
        sa.Column("precision", sa.Float(), nullable=True),
        sa.Column("recall", sa.Float(), nullable=True),
        sa.Column("f1", sa.Float(), nullable=True),
        sa.Column("false_merge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("false_split_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ambiguous_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cluster_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("benchmark_accuracy", sa.Float(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_identity_metrics_computed_at", "identity_metrics", ["computed_at"])
    op.create_index("ix_identity_metrics_scorer_version", "identity_metrics", ["scorer_version"])


def downgrade() -> None:
    op.drop_index("ix_identity_metrics_scorer_version", table_name="identity_metrics")
    op.drop_index("ix_identity_metrics_computed_at", table_name="identity_metrics")
    op.drop_table("identity_metrics")
    op.drop_index("ix_identity_benchmark_cases_case_key", table_name="identity_benchmark_cases")
    op.drop_table("identity_benchmark_cases")
    op.drop_index("ix_identity_training_examples_market_b", table_name="identity_training_examples")
    op.drop_index("ix_identity_training_examples_market_a", table_name="identity_training_examples")
    op.drop_table("identity_training_examples")
    op.drop_index("ix_identity_review_actions_acted_at", table_name="identity_review_actions")
    op.drop_index("ix_identity_review_actions_action", table_name="identity_review_actions")
    op.drop_index("ix_identity_review_actions_cluster_id", table_name="identity_review_actions")
    op.drop_table("identity_review_actions")
    op.drop_index("ix_identity_split_merge_history_acted_at", table_name="identity_split_merge_history")
    op.drop_index("ix_identity_split_merge_history_action", table_name="identity_split_merge_history")
    op.drop_table("identity_split_merge_history")
    op.drop_index("ix_identity_cluster_members_market", table_name="identity_cluster_members")
    op.drop_index("ix_identity_cluster_members_event", table_name="identity_cluster_members")
    op.drop_index("ix_identity_cluster_members_cluster", table_name="identity_cluster_members")
    op.drop_table("identity_cluster_members")
    op.drop_index("ix_event_identity_clusters_primary_event", table_name="event_identity_clusters")
    op.drop_index("ix_event_identity_clusters_type_status", table_name="event_identity_clusters")
    op.drop_index("ix_event_identity_clusters_status", table_name="event_identity_clusters")
    op.drop_index("ix_event_identity_clusters_identity_type", table_name="event_identity_clusters")
    op.drop_index("ix_event_identity_clusters_cluster_key", table_name="event_identity_clusters")
    op.drop_table("event_identity_clusters")
    op.drop_index("ix_event_templates_canonical_predicate", table_name="event_templates")
    op.drop_index("ix_event_templates_family_key", table_name="event_templates")
    op.drop_table("event_templates")
    op.drop_index("ix_canonical_deadlines_bucket_key", table_name="canonical_deadlines")
    op.drop_table("canonical_deadlines")
    op.drop_index("ix_canonical_sources_source_type", table_name="canonical_sources")
    op.drop_index("ix_canonical_sources_normalized_name", table_name="canonical_sources")
    op.drop_table("canonical_sources")
    op.drop_index("ix_canonical_entities_entity_type", table_name="canonical_entities")
    op.drop_index("ix_canonical_entities_normalized_name", table_name="canonical_entities")
    op.drop_table("canonical_entities")
