"""add_index_to_snapshots

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-04

"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_index("ix_orderbook_snapshots_captured_at", "orderbook_snapshots", ["captured_at"])

def downgrade() -> None:
    op.drop_index("ix_orderbook_snapshots_captured_at", table_name="orderbook_snapshots")
