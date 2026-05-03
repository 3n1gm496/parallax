"""identity provenance and autopsy label storage

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-02
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "market_event_links",
        sa.Column("link_reason", sa.String(length=100), nullable=False, server_default="platform_group_key"),
    )
    op.add_column(
        "market_event_links",
        sa.Column("provenance", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.add_column(
        "autopsy_records",
        sa.Column("labels", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )


def downgrade() -> None:
    op.drop_column("autopsy_records", "labels")
    op.drop_column("market_event_links", "provenance")
    op.drop_column("market_event_links", "link_reason")
