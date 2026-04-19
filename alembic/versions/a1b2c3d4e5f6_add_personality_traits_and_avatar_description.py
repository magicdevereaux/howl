"""Add personality_traits and avatar_description to users

Revision ID: a1b2c3d4e5f6
Revises: 246bc2dd05a6
Create Date: 2026-04-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '246bc2dd05a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('personality_traits', sa.JSON(), nullable=True))
    op.add_column('users', sa.Column('avatar_description', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'avatar_description')
    op.drop_column('users', 'personality_traits')
