"""add missing indexes on hot query paths

Covers GAPS #20.

- swipes.target_user_id — the reciprocal-like lookup on every swipe
  (app/api/swipes.py) and the block filters (app/api/blocks.py).
- messages.sender_id — the per-sender send rate-limit COUNT (app/api/chat.py)
  and the FK scanned on every user delete.
- reports.message_id — a SET NULL FK with no index, so every message delete
  scanned reports.
- messages (match_id, created_at) — chat pagination and the newest-message
  window function in app/api/users.py. Its leading column subsumes the old
  single-column ix_messages_match_id, which is dropped as redundant.

Revision ID: o6i7j8k9l0m1
Revises: n5h6i7j8k9l0
Create Date: 2026-08-06 00:00:00.000000

"""
from alembic import op

revision = 'o6i7j8k9l0m1'
down_revision = 'n5h6i7j8k9l0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_swipes_target_user_id', 'swipes', ['target_user_id'])
    op.create_index('ix_messages_sender_id', 'messages', ['sender_id'])
    op.create_index('ix_reports_message_id', 'reports', ['message_id'])

    op.create_index(
        'ix_messages_match_id_created_at', 'messages', ['match_id', 'created_at']
    )
    # Redundant now: (match_id, created_at) answers every match_id-only lookup.
    op.drop_index('ix_messages_match_id', table_name='messages')


def downgrade() -> None:
    op.create_index('ix_messages_match_id', 'messages', ['match_id'])
    op.drop_index('ix_messages_match_id_created_at', table_name='messages')

    op.drop_index('ix_reports_message_id', table_name='reports')
    op.drop_index('ix_messages_sender_id', table_name='messages')
    op.drop_index('ix_swipes_target_user_id', table_name='swipes')
