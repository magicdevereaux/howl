from fastapi import APIRouter, Depends
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

# Maps looking_for values to the corresponding gender stored on User rows.
_LOOKING_FOR_TO_GENDER = {
    "men": "man",
    "women": "woman",
    "non-binary": "non-binary",
}

from app.db import get_db
from app.dependencies import get_current_user
from app.models.block import Block
from app.models.match import Match
from app.models.message import Message
from app.models.swipe import Swipe
from app.models.user import AvatarStatus, User
from app.schemas.browse import BrowseUserOut
from app.schemas.swipe import DiscoverUserOut, LastMessageOut, MatchOut, MatchedProfileOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/browse", response_model=list[BrowseUserOut])
def browse_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[User]:
    """Return all users with a ready avatar, excluding the current user."""
    users = (
        db.query(User)
        .filter(
            User.id != current_user.id,
            User.avatar_status == AvatarStatus.ready,
        )
        .order_by(User.created_at.desc())
        .all()
    )
    return users


@router.get("/discover", response_model=list[DiscoverUserOut])
def discover_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[User]:
    """Return ready users the current user hasn't swiped on or blocked (either direction).

    Preference filtering is opt-in: a filter is only applied when the current
    user has set the corresponding preference.  Users who have not filled in
    their own age or gender are always included so incomplete profiles are not
    unfairly hidden.
    """
    swiped = (
        db.query(Swipe.target_user_id)
        .filter(Swipe.user_id == current_user.id)
        .scalar_subquery()
    )
    blocked_by_me = (
        db.query(Block.blocked_id)
        .filter(Block.blocker_id == current_user.id)
        .scalar_subquery()
    )
    blocking_me = (
        db.query(Block.blocker_id)
        .filter(Block.blocked_id == current_user.id)
        .scalar_subquery()
    )
    q = (
        db.query(User)
        .filter(
            User.id != current_user.id,
            User.avatar_status == AvatarStatus.ready,
            User.id.notin_(swiped),
            User.id.notin_(blocked_by_me),
            User.id.notin_(blocking_me),
        )
    )

    # Age range preference — include profiles that haven't set their age
    if current_user.age_preference_min is not None:
        q = q.filter(
            or_(User.age.is_(None), User.age >= current_user.age_preference_min)
        )
    if current_user.age_preference_max is not None:
        q = q.filter(
            or_(User.age.is_(None), User.age <= current_user.age_preference_max)
        )

    # Gender/looking_for — include profiles that haven't set their gender
    if current_user.looking_for and current_user.looking_for != "everyone":
        target_gender = _LOOKING_FOR_TO_GENDER.get(current_user.looking_for)
        if target_gender:
            q = q.filter(
                or_(User.gender.is_(None), User.gender == target_gender)
            )

    return q.order_by(User.created_at.desc()).all()


@router.get("/matches", response_model=list[MatchOut])
def list_matches(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MatchOut]:
    """Return all matches with unread count and last message in a single query.

    Replaces the previous N+1 loop (3 queries per match) with:
      - one CASE-based JOIN to resolve the other user without a subloop
      - one ROW_NUMBER window-function subquery to get the newest message per match
      - one correlated scalar subquery for the per-match unread count
    Total: one database round-trip regardless of match count.
    """
    uid = current_user.id

    # Resolve "the other participant" as a SQL expression so the JOIN is computed
    # in the database rather than fetched row-by-row in Python.
    other_id_col = case(
        (Match.user1_id == uid, Match.user2_id),
        else_=Match.user1_id,
    )

    # Rank every message within its match newest-first.
    # Selecting rn == 1 from this subquery gives the last message per match
    # without a separate query per match.
    ranked_msgs = (
        db.query(
            Message.match_id.label("match_id"),
            Message.sender_id.label("sender_id"),
            Message.content.label("content"),
            Message.created_at.label("created_at"),
            func.row_number()
            .over(
                partition_by=Message.match_id,
                order_by=Message.created_at.desc(),
            )
            .label("rn"),
        )
        .subquery("ranked_msgs")
    )

    # Correlated scalar subquery for unread count.
    # COUNT(*) always returns an integer (0 when no rows match), so this is
    # never NULL regardless of whether there are any messages in the match.
    unread_sq = (
        select(func.count())
        .where(
            Message.match_id == Match.id,
            Message.sender_id != uid,
            Message.read_at.is_(None),
        )
        .correlate(Match)
        .scalar_subquery()
    )

    rows = (
        db.query(
            Match,
            User,
            unread_sq.label("unread_count"),
            ranked_msgs.c.sender_id.label("last_sender_id"),
            ranked_msgs.c.content.label("last_content"),
            ranked_msgs.c.created_at.label("last_created_at"),
        )
        .join(User, User.id == other_id_col)
        .outerjoin(
            ranked_msgs,
            (ranked_msgs.c.match_id == Match.id) & (ranked_msgs.c.rn == 1),
        )
        .filter(or_(Match.user1_id == uid, Match.user2_id == uid))
        .order_by(Match.matched_at.desc())
        .all()
    )

    return [
        MatchOut(
            id=match.id,
            matched_at=match.matched_at,
            other_user=MatchedProfileOut.model_validate(other),
            unread_count=unread_count or 0,
            last_message=(
                LastMessageOut(
                    sender_id=last_sender_id,
                    content=last_content,
                    created_at=last_created_at,
                )
                if last_content is not None else None
            ),
        )
        for match, other, unread_count, last_sender_id, last_content, last_created_at in rows
    ]
