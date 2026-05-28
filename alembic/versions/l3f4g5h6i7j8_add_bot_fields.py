"""add is_bot and archetype to users

Revision ID: l3f4g5h6i7j8
Revises: k2e3f4g5h6i7
Create Date: 2026-05-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'l3f4g5h6i7j8'
down_revision = 'k2e3f4g5h6i7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_bot', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('archetype', sa.String(50), nullable=True))
    op.create_index('ix_users_is_bot', 'users', ['is_bot'])


def downgrade() -> None:
    op.drop_index('ix_users_is_bot', table_name='users')
    op.drop_column('users', 'archetype')
    op.drop_column('users', 'is_bot')
