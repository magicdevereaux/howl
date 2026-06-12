"""add push_tokens table

Revision ID: n5h6i7j8k9l0
Revises: m4g5h6i7j8k9
Create Date: 2026-06-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'n5h6i7j8k9l0'
down_revision = 'm4g5h6i7j8k9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'push_tokens',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('token', name='uq_push_tokens_token'),
    )
    op.create_index('ix_push_tokens_user_id', 'push_tokens', ['user_id'])
    op.create_index('ix_push_tokens_token', 'push_tokens', ['token'])


def downgrade() -> None:
    op.drop_index('ix_push_tokens_token', table_name='push_tokens')
    op.drop_index('ix_push_tokens_user_id', table_name='push_tokens')
    op.drop_table('push_tokens')
