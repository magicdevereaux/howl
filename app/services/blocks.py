"""Shared block-relationship lookup.

`Block` used to be consulted in exactly one place — the two `notin_`
subqueries in `discover_users` — which made blocking *effective* for chat only
as a side effect of `block_user` also deleting the match and both swipe rows
(no match means `_require_match_member` 404s). Nothing else checked the table,
so a blocked party could still load the blocker's profile by id
(`GET /api/profile/{user_id}`) or bank a `like` against them
(`POST /api/swipes`) that would resolve into an instant match the moment the
block was lifted.

`blocked_between` is the single predicate both of those call sites now share,
so "does a block exist in either direction" cannot drift between them the way
the enforcement itself already had.
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.block import Block


def blocked_between(db: Session, a_id: int, b_id: int) -> bool:
    """True if either user has blocked the other."""
    return (
        db.query(Block.id)
        .filter(
            or_(
                (Block.blocker_id == a_id) & (Block.blocked_id == b_id),
                (Block.blocker_id == b_id) & (Block.blocked_id == a_id),
            )
        )
        .first()
        is not None
    )
