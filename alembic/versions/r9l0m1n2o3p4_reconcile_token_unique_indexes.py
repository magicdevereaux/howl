"""collapse the token tables' index + unique constraint into one unique index

Covers GAPS #21.

The three token tables each declare ``unique=True, index=True`` on ``token``,
which in SQLAlchemy metadata is a *single unique index* named ``ix_<table>_token``.
Their migrations instead created a plain non-unique index of that name plus a
separately named UniqueConstraint, so the database carried two objects where the
models describe one — and ``alembic revision --autogenerate`` wanted to drop and
rebuild all of them on every run.

The database is brought to the models' shape rather than the reverse: one unique
index per token column. On Postgres the redundant object was real overhead — the
UniqueConstraint is itself backed by an index, so each of these tables was
maintaining two indexes over the same column on every insert.

users.email is already consistent (246bc2dd05a6 created it unique) and needs no
change, despite GAPS #21 counting four tables.

Revision ID: r9l0m1n2o3p4
Revises: q8k9l0m1n2o3
Create Date: 2026-08-06 00:00:00.000000

"""
from alembic import op

revision = 'r9l0m1n2o3p4'
down_revision = 'q8k9l0m1n2o3'
branch_labels = None
depends_on = None

# (table, name of the redundant UniqueConstraint)
_TOKEN_TABLES = (
    ('refresh_tokens', 'uq_refresh_token'),
    ('password_reset_tokens', 'uq_password_reset_token'),
    ('push_tokens', 'uq_push_tokens_token'),
)


def upgrade() -> None:
    for table, uq_name in _TOKEN_TABLES:
        # Drop the plain index first so uniqueness is never unenforced.
        op.drop_index(f'ix_{table}_token', table_name=table)
        op.create_index(f'ix_{table}_token', table, ['token'], unique=True)
        op.drop_constraint(uq_name, table, type_='unique')


def downgrade() -> None:
    for table, uq_name in _TOKEN_TABLES:
        op.create_unique_constraint(uq_name, table, ['token'])
        op.drop_index(f'ix_{table}_token', table_name=table)
        op.create_index(f'ix_{table}_token', table, ['token'])
