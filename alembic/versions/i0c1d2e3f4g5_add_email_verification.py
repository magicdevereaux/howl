"""add email verification fields to users

Revision ID: i0c1d2e3f4g5
Revises: h9b0c1d2e3f4
Create Date: 2026-05-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'i0c1d2e3f4g5'
down_revision = 'h9b0c1d2e3f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_email_verified', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('email_verification_token', sa.String(64), nullable=True))
    op.add_column('users', sa.Column('email_verification_token_expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'email_verification_token_expires_at')
    op.drop_column('users', 'email_verification_token')
    op.drop_column('users', 'is_email_verified')
