"""lowercase existing user emails

Revision ID: m4g5h6i7j8k9
Revises: l3f4g5h6i7j8
Create Date: 2026-06-11 00:00:00.000000

"""
from alembic import op

revision = 'm4g5h6i7j8k9'
down_revision = 'l3f4g5h6i7j8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET email = LOWER(email) WHERE email <> LOWER(email)")


def downgrade() -> None:
    # Original casing is not preserved, so this cannot be reversed.
    pass
