import logging
import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.match import Match
from app.models.swipe import Swipe, SwipeDirection
from app.models.user import User
from app.schemas.swipe import DiscoverUserOut, MatchOut, MatchedProfileOut, SwipeIn, SwipeOut, UndoSwipeOut
from app.tasks.auto_match import auto_match_demo_user

logger = logging.getLogger(__name__)

# Seconds to wait before the demo user "responds". Change to random.randint(600, 3600)
# (10–60 min) for production; 30 s is convenient for local testing.
_DEMO_REPLY_DELAY_S = 30

router = APIRouter(prefix="/api/swipes", tags=["swipes"])


@router.post("", response_model=SwipeOut, status_code=200)
def record_swipe(
    body: SwipeIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SwipeOut:
    """Record a like or pass, and create a Match if mutual like."""
    if body.target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot swipe on yourself.")

    target = db.query(User).filter(User.id == body.target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    existing = (
        db.query(Swipe)
        .filter(Swipe.user_id == current_user.id, Swipe.target_user_id == body.target_user_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already swiped on this user.")

    swipe = Swipe(
        user_id=current_user.id,
        target_user_id=body.target_user_id,
        direction=body.direction,
    )
    db.add(swipe)
    db.flush()

    matched = False
    match_out = None

    if body.direction == SwipeDirection.like:
        mutual = (
            db.query(Swipe)
            .filter(
                Swipe.user_id == body.target_user_id,
                Swipe.target_user_id == current_user.id,
                Swipe.direction == SwipeDirection.like,
            )
            .first()
        )
        if mutual:
            u1 = min(current_user.id, body.target_user_id)
            u2 = max(current_user.id, body.target_user_id)
            match = Match(user1_id=u1, user2_id=u2)
            db.add(match)
            db.flush()
            matched = True
            other_profile = MatchedProfileOut.model_validate(target)
            match_out = MatchOut(
                id=match.id,
                matched_at=match.matched_at,
                other_user=other_profile,
            )

    db.commit()

    # Queue a delayed auto-like if the target is a demo user and we just liked them.
    # The task itself re-validates everything, so it's safe to fire and forget.
    if body.direction == SwipeDirection.like and target.email.startswith("demo"):
        auto_match_demo_user.apply_async(
            args=[current_user.id, body.target_user_id],
            countdown=_DEMO_REPLY_DELAY_S,
        )
        logger.info(
            "swipes: queued auto_match in %ds for real=%d demo=%d",
            _DEMO_REPLY_DELAY_S, current_user.id, body.target_user_id,
        )

    return SwipeOut(matched=matched, match=match_out)


@router.delete("/last", response_model=UndoSwipeOut, status_code=200)
def undo_last_swipe(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UndoSwipeOut:
    """
    Delete the current user's most recent swipe.

    If that swipe was a like that created a match, the match is deleted too.
    For demo user auto-matches, the demo's return-swipe is also removed so
    the discover queue is fully restored to its pre-swipe state.

    Returns the deleted swipe's target user so the frontend can push them
    back to the front of the discover stack.
    """
    last_swipe = (
        db.query(Swipe)
        .filter(Swipe.user_id == current_user.id)
        .order_by(Swipe.created_at.desc())
        .first()
    )
    if last_swipe is None:
        raise HTTPException(status_code=404, detail="No swipes to undo.")

    target = db.query(User).filter(User.id == last_swipe.target_user_id).first()
    # Snapshot the values we need before deletion
    target_user_id = last_swipe.target_user_id
    direction = last_swipe.direction

    if direction == SwipeDirection.like:
        u1 = min(current_user.id, target_user_id)
        u2 = max(current_user.id, target_user_id)
        match = (
            db.query(Match)
            .filter(Match.user1_id == u1, Match.user2_id == u2)
            .first()
        )
        if match:
            db.delete(match)
            # Also remove the other party's swipe (demo auto-match or a real mutual like)
            # so both users are fully restored to pre-swipe state.
            return_swipe = (
                db.query(Swipe)
                .filter(
                    Swipe.user_id == target_user_id,
                    Swipe.target_user_id == current_user.id,
                )
                .first()
            )
            if return_swipe:
                db.delete(return_swipe)

    db.delete(last_swipe)
    db.commit()

    logger.info(
        "swipes: undid %s swipe by user=%d on target=%d",
        direction.value, current_user.id, target_user_id,
    )

    return UndoSwipeOut(
        target_user_id=target_user_id,
        direction=direction,
        user=DiscoverUserOut.model_validate(target),
    )
