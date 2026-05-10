"""add preference fields to users

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-05-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f7a8b9c0d1e2'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('gender', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('sexuality', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('looking_for', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('age_preference_min', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('age_preference_max', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'age_preference_max')
    op.drop_column('users', 'age_preference_min')
    op.drop_column('users', 'looking_for')
    op.drop_column('users', 'sexuality')
    op.drop_column('users', 'gender')
