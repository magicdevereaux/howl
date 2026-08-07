"""give every creation timestamp a server_default of now()

Covers the safe half of GAPS #22.

Every DateTime column in the app had a Python-side default and no
server_default, which means:

  - a raw-SQL or bulk INSERT that omits created_at violates NOT NULL, so the
    columns were only insertable through the ORM;
  - the value recorded is the *app host's* clock, so timestamps from different
    replicas (web, Celery worker, Beat) carry relative skew.

now() is added to the ten creation timestamps. The Python defaults stay: when a
column has both, SQLAlchemy uses the Python one for ORM inserts, so nothing
about existing behaviour changes — the server default is the floor for writers
that bypass the ORM.

Deliberately untouched: expires_at (no default is correct — the caller decides
the lifetime) and every nullable timestamp (read_at, deleted_at,
avatar_status_updated_at, swipes_reset_at, regenerations_reset_at,
email_verification_token_expires_at), where NULL is a meaningful state and a
default would destroy it. users.updated_at gets now() as its *initial* value
only; the onupdate remains Python-side, since a server-side equivalent needs a
trigger.

Revision ID: s0m1n2o3p4q5
Revises: r9l0m1n2o3p4
Create Date: 2026-08-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 's0m1n2o3p4q5'
down_revision = 'r9l0m1n2o3p4'
branch_labels = None
depends_on = None

# (table, column)
_TIMESTAMPS = (
    ('users', 'created_at'),
    ('users', 'updated_at'),
    ('swipes', 'created_at'),
    ('matches', 'matched_at'),
    ('messages', 'created_at'),
    ('blocks', 'created_at'),
    ('reports', 'created_at'),
    ('refresh_tokens', 'created_at'),
    ('password_reset_tokens', 'created_at'),
    ('push_tokens', 'created_at'),
)


def upgrade() -> None:
    for table, column in _TIMESTAMPS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
            server_default=sa.text('now()'),
        )


def downgrade() -> None:
    for table, column in _TIMESTAMPS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=False,
            server_default=None,
        )
