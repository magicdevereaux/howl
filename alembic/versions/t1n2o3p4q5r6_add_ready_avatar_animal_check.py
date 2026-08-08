"""tie avatar_status='ready' to a non-null animal

Closes the last deferred bullet of GAPS #23.

#23 deferred this with a reason: "the avatar pipeline writes these in more than
one step, so a CHECK would need the whole transition to be transactional first."
That was checked before adding the constraint, and the transition turns out to
already be atomic at every writer:

  - app/tasks/avatar.py sets animal, personality_traits, avatar_description,
    avatar_url and avatar_status='ready' against the session and commits once.
  - app/api/avatar.py (regenerate) and app/api/profile.py (bio change) both clear
    animal/avatar_url and set status='pending' in a single commit. The only
    db.flush() on either path is inside the regeneration-limit check, which runs
    *before* any avatar field is touched, so it flushes a row that is still in
    its previous consistent state.

So no restructuring was needed; the invariant already held at every commit
boundary and this migration makes it the database's job. task_acks_late means a
killed task re-runs from the top, which is safe here for the same reason: a
re-run either skips (already ready) or redoes the whole single-commit write.

Scope: `animal`, NOT `avatar_url`
---------------------------------
"ready implies avatar_url IS NOT NULL" would have been the intuitive constraint
and it is false. Two legitimate states hold ready with a NULL url:

  1. the 1000 bots from scripts/seed_demo_users.py, which set
     avatar_status=ready and avatar_url=None and render from `animal` alone.
     A url-based CHECK would abort every production deploy's seed step.
  2. generate_avatar treats image generation as best-effort — DALL-E failing, or
     not being configured at all, yields avatar_url=None and the profile still
     goes ready with an emoji fallback.

`animal` is the one field that is genuinely always present on a ready row, and
it is the one the discover queue depends on: app/api/users.py admits a profile
purely on avatar_status='ready', and the clients fall back to a generic emoji
rather than erroring, so a ready-but-animal-less row would sit in a thousand
people's queues without ever raising anything.

The pre-flight UPDATE demotes any violating row to 'failed' rather than deleting
or inventing an animal. 'failed' is the honest description of a profile whose
generation never produced an animal, and it is a state the app already recovers
from: POST /api/avatar/regenerate re-queues generation. It should never match
anything, since the invariant has held in application code from the start.

Revision ID: t1n2o3p4q5r6
Revises: s0m1n2o3p4q5
Create Date: 2026-08-08 00:00:00.000000

"""
from alembic import op

revision = 't1n2o3p4q5r6'
down_revision = 's0m1n2o3p4q5'
branch_labels = None
depends_on = None

_CONSTRAINT = 'ck_users_ready_avatar_has_animal'
_CONDITION = "avatar_status <> 'ready' OR animal IS NOT NULL"


def upgrade() -> None:
    # Defensive: demote rather than abort halfway through the ALTER. See the
    # module docstring for why 'failed' is the right landing state.
    op.execute(
        "UPDATE users SET avatar_status = 'failed' "
        "WHERE avatar_status = 'ready' AND animal IS NULL"
    )
    op.create_check_constraint(_CONSTRAINT, 'users', _CONDITION)


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, 'users', type_='check')
