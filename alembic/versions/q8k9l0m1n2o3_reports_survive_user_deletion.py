"""make reports survive user deletion

Covers GAPS #24.

reports.message_id was already ON DELETE SET NULL "so reports survive message
deletion", but reporter_id and reported_user_id were ON DELETE CASCADE — so the
single deletion that matters most for moderation, an abuser deleting their own
account, erased every report filed against them.

Both user FKs become ON DELETE SET NULL and the columns become nullable. The
report row, its reason, notes and timestamp survive; the identities do not, so
account deletion still removes the user's personal data.

Revision ID: q8k9l0m1n2o3
Revises: p7j8k9l0m1n2
Create Date: 2026-08-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'q8k9l0m1n2o3'
down_revision = 'p7j8k9l0m1n2'
branch_labels = None
depends_on = None

# Postgres auto-generated names for the inline FKs created in e6f7a8b9c0d1.
_REPORTER_FK = 'reports_reporter_id_fkey'
_REPORTED_FK = 'reports_reported_user_id_fkey'


def upgrade() -> None:
    op.alter_column('reports', 'reporter_id', existing_type=sa.Integer(), nullable=True)
    op.alter_column('reports', 'reported_user_id', existing_type=sa.Integer(), nullable=True)

    op.drop_constraint(_REPORTER_FK, 'reports', type_='foreignkey')
    op.drop_constraint(_REPORTED_FK, 'reports', type_='foreignkey')
    op.create_foreign_key(
        _REPORTER_FK, 'reports', 'users', ['reporter_id'], ['id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        _REPORTED_FK, 'reports', 'users', ['reported_user_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    # Rows anonymised while the SET NULL behaviour was live cannot be made
    # NOT NULL again, so they are dropped. This is the only lossy step, and it
    # only discards reports whose subject no longer exists.
    op.execute(
        "DELETE FROM reports WHERE reporter_id IS NULL OR reported_user_id IS NULL"
    )

    op.drop_constraint(_REPORTED_FK, 'reports', type_='foreignkey')
    op.drop_constraint(_REPORTER_FK, 'reports', type_='foreignkey')
    op.create_foreign_key(
        _REPORTER_FK, 'reports', 'users', ['reporter_id'], ['id'], ondelete='CASCADE'
    )
    op.create_foreign_key(
        _REPORTED_FK, 'reports', 'users', ['reported_user_id'], ['id'], ondelete='CASCADE'
    )

    op.alter_column('reports', 'reported_user_id', existing_type=sa.Integer(), nullable=False)
    op.alter_column('reports', 'reporter_id', existing_type=sa.Integer(), nullable=False)
