"""dedup reports on (reporter_id, reported_user_id, message_id)

Covers GAPS #53.

POST /api/reports had no rate limit and no dedup, and validated a submitted
message_id by loading the message and checking sender identity without ever
checking that the *reporter* is a participant in that message's match. Any
authenticated user could walk message_id = 1..N against a chosen victim and
learn exactly which messages that person wrote from the three distinguishable
outcomes (404 nonexistent / 400 wrong author / 200 filed), and every probe
also wrote a permanent moderation-queue row (reports survive account deletion
per GAPS #24). The application fix (app/api/reports.py) requires match
membership and rate-limits the endpoint; this migration adds the matching
database-level dedup so a repeated submission against the same target updates
the existing row instead of creating a new one, per-row, forever.

A plain UNIQUE(reporter_id, reported_user_id, message_id) does not work:
ordinary SQL treats every NULL as distinct from every other NULL, so it would
never catch two profile-level reports (message_id IS NULL, no specific
message) against the same target -- the case a sequential-id sweep of
`POST /api/reports` with no message_id would still exploit freely. The index
is keyed on COALESCE(message_id, -1) instead so a NULL message_id becomes a
single comparable value. -1 is a safe sentinel: message ids are positive
autoincrement integers.

Deliberately scoped to reporter_id IS NOT NULL AND reported_user_id IS NOT
NULL. Both columns go NULL on deletion of the user they reference (GAPS #24
made every FK here ON DELETE SET NULL so a report outlives the rows it points
at) -- those rows are historical evidence, not live submissions, and two
unrelated anonymised reports must not be forced to collide just because both
lost their identifying columns.

Existing rows may already violate the constraint (nothing has ever prevented
duplicate profile-level reports). The pre-flight DELETE keeps the newest row
per (reporter_id, reported_user_id, COALESCE(message_id, -1)) group -- among
rows where both id columns are still populated -- and drops the older
duplicates. This is lossy on downgrade: a duplicate's reason/notes, once
merged away by this migration, cannot be un-merged. Given every surviving
report already documents the same reporter reporting the same target (and,
where applicable, the same message), the discarded rows added no information
the newest one didn't already carry.

Revision ID: u2o3p4q5r6s7
Revises: t1n2o3p4q5r6
Create Date: 2026-08-09 00:00:00.000000

"""
from alembic import op

revision = 'u2o3p4q5r6s7'
down_revision = 't1n2o3p4q5r6'
branch_labels = None
depends_on = None

_INDEX = 'uq_reports_reporter_target_message'


def upgrade() -> None:
    # Keep the newest row per group; drop older duplicates so the unique index
    # below can be created. Anonymised rows (either id column NULL) are exempt
    # -- see the module docstring.
    op.execute(
        """
        DELETE FROM reports r
        USING reports newer
        WHERE r.reporter_id IS NOT NULL
          AND r.reported_user_id IS NOT NULL
          AND r.reporter_id = newer.reporter_id
          AND r.reported_user_id = newer.reported_user_id
          AND COALESCE(r.message_id, -1) = COALESCE(newer.message_id, -1)
          AND r.id < newer.id
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
        ON reports (reporter_id, reported_user_id, COALESCE(message_id, -1))
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX {_INDEX}")
