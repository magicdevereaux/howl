"""add avatar regeneration limit fields to users

Revision ID: j1d2e3f4g5h6
Revises: i0c1d2e3f4g5
Create Date: 2026-05-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'j1d2e3f4g5h6'
down_revision = 'i0c1d2e3f4g5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('avatar_regenerations_this_month', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('regenerations_reset_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'regenerations_reset_at')
    op.drop_column('users', 'avatar_regenerations_this_month')
