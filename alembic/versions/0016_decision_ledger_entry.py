"""decision ledger entry for candidate snapshots

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-04
"""

from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_decision_snapshots",
        sa.Column("decision_ledger_entry", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_decision_snapshots", "decision_ledger_entry")
