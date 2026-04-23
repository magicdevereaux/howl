"""add swipes and matches tables

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-04-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a1b2c3'
down_revision = 'c3d4e5f6a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'swipes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('target_user_id', sa.Integer(), nullable=False),
        sa.Column('direction', sa.Enum('like', 'pass', name='swipe_direction'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'target_user_id', name='uq_swipe_user_target'),
    )
    op.create_index('ix_swipes_user_id', 'swipes', ['user_id'])

    op.create_table(
        'matches',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user1_id', sa.Integer(), nullable=False),
        sa.Column('user2_id', sa.Integer(), nullable=False),
        sa.Column('matched_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user1_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user2_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user1_id', 'user2_id', name='uq_match_users'),
    )
    op.create_index('ix_matches_user1_id', 'matches', ['user1_id'])
    op.create_index('ix_matches_user2_id', 'matches', ['user2_id'])


def downgrade() -> None:
    op.drop_index('ix_matches_user2_id', table_name='matches')
    op.drop_index('ix_matches_user1_id', table_name='matches')
    op.drop_table('matches')
    op.drop_index('ix_swipes_user_id', table_name='swipes')
    op.drop_table('swipes')
    op.execute("DROP TYPE IF EXISTS swipe_direction")
