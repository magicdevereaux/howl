"""add name and location to users

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-04-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a1b2'
down_revision = 'b2c3d4e5f6a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('name', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('location', sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'location')
    op.drop_column('users', 'name')
