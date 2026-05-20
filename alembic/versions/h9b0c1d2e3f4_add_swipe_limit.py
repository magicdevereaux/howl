"""add swipe limit fields to users

Revision ID: h9b0c1d2e3f4
Revises: g8a9b0c1d2e3
Create Date: 2026-05-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'h9b0c1d2e3f4'
down_revision = 'g8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_premium', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('daily_swipes', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('swipes_reset_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'swipes_reset_at')
    op.drop_column('users', 'daily_swipes')
    op.drop_column('users', 'is_premium')
