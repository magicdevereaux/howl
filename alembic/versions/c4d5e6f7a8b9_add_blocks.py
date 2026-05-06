"""add blocks table

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-05-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'blocks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('blocker_id', sa.Integer(), nullable=False),
        sa.Column('blocked_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['blocker_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['blocked_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('blocker_id', 'blocked_id', name='uq_block_pair'),
    )
    op.create_index('ix_blocks_blocker_id', 'blocks', ['blocker_id'])
    op.create_index('ix_blocks_blocked_id', 'blocks', ['blocked_id'])


def downgrade() -> None:
    op.drop_index('ix_blocks_blocked_id', table_name='blocks')
    op.drop_index('ix_blocks_blocker_id', table_name='blocks')
    op.drop_table('blocks')
