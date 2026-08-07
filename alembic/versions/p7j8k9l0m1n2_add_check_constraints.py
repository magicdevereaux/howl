"""add CHECK constraints for match ordering and the 18+ age gate

Covers part of GAPS #23.

- matches: the "user1_id < user2_id" canonical form was only a comment. Every
  writer already does min()/max(), but uq_match_users alone cannot stop the
  same pair being stored twice as (a, b) and (b, a).
- users: the 18+ gate lived only in ProfileUpdate.validate_age. NULL is still
  allowed — registration takes email and password only, so every account
  starts ageless. Making the column NOT NULL is deliberately *not* done here;
  see the report / GAPS #23.

Both statements are preceded by a defensive normalisation of existing rows.
Neither should ever match anything, since both invariants have been enforced in
the application layer from the start; they exist so the migration fails loudly
on real drift rather than aborting halfway through the ALTER.

Revision ID: p7j8k9l0m1n2
Revises: o6i7j8k9l0m1
Create Date: 2026-08-06 00:00:00.000000

"""
from alembic import op

revision = 'p7j8k9l0m1n2'
down_revision = 'o6i7j8k9l0m1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A single UPDATE swaps correctly: every SET expression sees the old row.
    # If an inverted row has a canonical twin this trips uq_match_users, which
    # is the right outcome — that needs a human, not a silent delete.
    op.execute(
        "UPDATE matches SET user1_id = user2_id, user2_id = user1_id "
        "WHERE user1_id > user2_id"
    )
    op.create_check_constraint(
        'ck_matches_user_order', 'matches', 'user1_id < user2_id'
    )

    # Clearing an out-of-range age rather than deleting the account: it sends
    # the user back through onboarding, which is where the gate belongs.
    op.execute(
        "UPDATE users SET age = NULL WHERE age IS NOT NULL AND (age < 18 OR age > 120)"
    )
    op.create_check_constraint(
        'ck_users_age_range', 'users', 'age IS NULL OR (age >= 18 AND age <= 120)'
    )


def downgrade() -> None:
    op.drop_constraint('ck_users_age_range', 'users', type_='check')
    op.drop_constraint('ck_matches_user_order', 'matches', type_='check')
