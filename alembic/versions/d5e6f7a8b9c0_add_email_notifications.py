"""add email_notifications to users

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-05-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'email_notifications',
            sa.Boolean(),
            nullable=False,
            server_default='true',
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'email_notifications')
