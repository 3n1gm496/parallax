"""add_contract_fingerprints_to_certificate

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-04

"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("trade_proof_certificates", sa.Column("contract_fingerprints", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")))

def downgrade() -> None:
    op.drop_column("trade_proof_certificates", "contract_fingerprints")
