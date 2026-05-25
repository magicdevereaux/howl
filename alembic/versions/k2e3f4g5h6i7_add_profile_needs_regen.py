"""add profile_needs_regen to users

Revision ID: k2e3f4g5h6i7
Revises: j1d2e3f4g5h6
Create Date: 2026-05-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'k2e3f4g5h6i7'
down_revision = 'j1d2e3f4g5h6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('profile_needs_regen', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('users', 'profile_needs_regen')
