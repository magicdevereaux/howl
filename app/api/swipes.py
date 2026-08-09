import logging
from datetime import UTC, datetime, timedelta
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.db import get_db
from app.dependencies import require_verified_email
from app.models.match import Match
from app.models.swipe import Swipe, SwipeDirection
from app.models.user import User
from app.schemas.swipe import (
    DiscoverUserOut,
    MatchedProfileOut,
    MatchOut,
    SwipeIn,
    SwipeOut,
    UndoSwipeOut,
)
from app.tasks.auto_match import auto_match_demo_user
from app.tasks.notify import notify_new_match

logger = logging.getLogger(__name__)

_DEMO_REPLY_DELAY_S = 30        # see comment on auto_match task
_DAILY_SWIPE_LIMIT = 20         # free-tier swipes per 24-hour window
_SWIPE_WINDOW_SECONDS = 86400   # 24 h

router = APIRouter(prefix="/api/swipes", tags=["swipes"])


# ---------------------------------------------------------------------------
# Daily swipe quota
#
# Concurrency note: every invariant here is enforced by the database, not by
# reading a value into Python and acting on it.  Two requests from the same
# account can interleave arbitrarily (multiple uvicorn workers, or a
# double-tapped button), so a check-then-write would let both through.
#   - the quota is consumed by one conditional UPDATE whose rowcount is the
#     authority (`_consume_swipe_quota`)
#   - duplicate swipes are rejected by `uq_swipe_user_target`
#   - duplicate matches are rejected by `uq_match_users`
# ---------------------------------------------------------------------------

def _normalise(dt: datetime | None) -> datetime | None:
    """Attach UTC to a naive timestamp.

    Columns are ``DateTime(timezone=True)`` with Python-side defaults and no
    ``server_default``, so SQLite (the whole test suite) reads them back naive.
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _window_expired(now: datetime) -> ColumnElement[bool]:
    """SQL predicate: this user's 24-hour swipe window has rolled over."""
    cutoff = now - timedelta(seconds=_SWIPE_WINDOW_SECONDS)
    return or_(User.swipes_reset_at.is_(None), User.swipes_reset_at <= cutoff)


def _raise_daily_limit(reset_at: datetime | None) -> NoReturn:
    base = _normalise(reset_at) or datetime.now(UTC)
    resets_at = base + timedelta(seconds=_SWIPE_WINDOW_SECONDS)
    raise HTTPException(
        status_code=429,
        detail={
            "code": "daily_limit_reached",
            "message": (
                f"You've used all {_DAILY_SWIPE_LIMIT} free swipes for today. "
                "Upgrade to premium for unlimited swiping."
            ),
            "limit": _DAILY_SWIPE_LIMIT,
            "resets_at": resets_at.isoformat(),
        },
    )


def _check_swipe_limit(user: User) -> None:
    """Read-only pre-flight so an over-quota user is refused before any write.

    This is deliberately *only* an early-out — it reads values that another
    concurrent request may already have changed.  `_consume_swipe_quota` is the
    authority.  Only called for non-premium users.
    """
    reset_at = _normalise(user.swipes_reset_at)
    if reset_at is None:
        return  # never swiped — the window opens on this swipe
    if (datetime.now(UTC) - reset_at).total_seconds() >= _SWIPE_WINDOW_SECONDS:
        return  # window rolled over, the counter is about to reset
    if user.daily_swipes >= _DAILY_SWIPE_LIMIT:
        _raise_daily_limit(reset_at)


def _consume_swipe_quota(user_id: int, db: Session) -> bool:
    """Atomically claim one swipe from the daily quota.

    A single ``UPDATE ... WHERE`` does the window rollover and the increment
    together, so there is no window between deciding and writing.  Returns
    False when no row matched, meaning the quota was already exhausted — under
    concurrency the database serialises the row and re-evaluates the predicate,
    so exactly `_DAILY_SWIPE_LIMIT` requests can win per window.
    """
    now = datetime.now(UTC)
    expired = _window_expired(now)
    stmt = (
        update(User)
        .where(
            User.id == user_id,
            or_(expired, User.daily_swipes < _DAILY_SWIPE_LIMIT),
        )
        .values(
            daily_swipes=case((expired, 1), else_=User.daily_swipes + 1),
            swipes_reset_at=case((expired, now), else_=User.swipes_reset_at),
        )
    )
    # synchronize_session=False: the ORM's "evaluate" strategy cannot compare the
    # tz-aware bound cutoff against the naive value SQLite hands back.  The
    # commit at the end of the request expires the instance anyway.
    result = db.execute(stmt, execution_options={"synchronize_session": False})
    return bool(result.rowcount)


# ---------------------------------------------------------------------------
# Writes guarded by unique constraints
# ---------------------------------------------------------------------------

def _insert_swipe(
    db: Session, user_id: int, target_user_id: int, direction: SwipeDirection
) -> Swipe:
    """Insert a swipe, letting `uq_swipe_user_target` reject duplicates.

    The insert runs inside a SAVEPOINT so a constraint violation does not
    poison the surrounding transaction while we work out which invariant was
    hit.  Raises 409 for a duplicate swipe, 404 if the target disappeared.
    """
    swipe = Swipe(user_id=user_id, target_user_id=target_user_id, direction=direction)
    try:
        with db.begin_nested():
            db.add(swipe)
            db.flush()
    except IntegrityError:
        duplicate = (
            db.query(Swipe.id)
            .filter(Swipe.user_id == user_id, Swipe.target_user_id == target_user_id)
            .first()
        )
        if duplicate is not None:
            logger.info(
                "swipes: concurrent duplicate swipe user=%d target=%d", user_id, target_user_id
            )
            db.rollback()
            raise HTTPException(status_code=409, detail="Already swiped on this user.") from None
        if db.query(User.id).filter(User.id == target_user_id).first() is None:
            db.rollback()
            raise HTTPException(status_code=404, detail="User not found.") from None
        raise
    return swipe


def _get_or_create_match(db: Session, a_id: int, b_id: int) -> tuple[Match, bool]:
    """Return the match between two users, creating it if it doesn't exist.

    `uq_match_users` makes this safe when both users like each other at the
    same instant: the loser of the insert race reads the winner's row instead
    of writing a second one.  Returns ``(match, created_by_us)`` so only the
    creator sends the new-match notification.
    """
    u1, u2 = min(a_id, b_id), max(a_id, b_id)
    match = Match(user1_id=u1, user2_id=u2)
    try:
        with db.begin_nested():
            db.add(match)
            db.flush()
        return match, True
    except IntegrityError:
        existing = (
            db.query(Match)
            .filter(Match.user1_id == u1, Match.user2_id == u2)
            .one_or_none()
        )
        if existing is None:
            raise
        logger.info("swipes: match %d already existed for (%d,%d)", existing.id, u1, u2)
        return existing, False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=SwipeOut, status_code=200)
def record_swipe(
    body: SwipeIn,
    current_user: User = Depends(require_verified_email),
    db: Session = Depends(get_db),
) -> SwipeOut:
    """Record a like or pass, and create a Match if mutual like.

    Gated on email verification (GAPS #25): swiping is outbound — it can create
    a match and notify a stranger — so it closes once the grace window expires.
    Reading the discover feed stays open.
    """
    if body.target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot swipe on yourself.")

    if not current_user.is_premium:
        _check_swipe_limit(current_user)

    target = db.query(User).filter(User.id == body.target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    # The swipe row is the dedup gate: if it inserts, this request owns the swipe.
    _insert_swipe(db, current_user.id, body.target_user_id, body.direction)

    # Charge the quota only once the swipe is genuinely ours.  Losing here means
    # a concurrent request took the last slot after our pre-flight check passed,
    # so the whole transaction — swipe included — is rolled back.
    if not current_user.is_premium and not _consume_swipe_quota(current_user.id, db):
        db.rollback()
        reset_at = (
            db.query(User.swipes_reset_at).filter(User.id == current_user.id).scalar()
        )
        logger.info("swipes: user=%d lost the quota race", current_user.id)
        _raise_daily_limit(reset_at)

    matched = False
    match_created = False
    match_id: int | None = None
    match_out = None

    if body.direction == SwipeDirection.like:
        mutual = (
            db.query(Swipe.id)
            .filter(
                Swipe.user_id == body.target_user_id,
                Swipe.target_user_id == current_user.id,
                Swipe.direction == SwipeDirection.like,
            )
            .first()
        )
        if mutual:
            match, match_created = _get_or_create_match(
                db, current_user.id, body.target_user_id
            )
            matched = True
            match_id = match.id
            match_out = MatchOut(
                id=match.id,
                matched_at=match.matched_at,
                other_user=MatchedProfileOut.model_validate(target),
            )

    db.commit()

    # Notify the other user that they have a new match.  Only the request that
    # actually created the row notifies, so a match race sends one push, not two.
    if match_created and match_id is not None:
        notify_new_match.delay(match_id, body.target_user_id)

    # Queue a delayed auto-like if the target is a demo user and we just liked them.
    # The task itself re-validates everything, so it's safe to fire and forget.
    if body.direction == SwipeDirection.like and target.is_bot:
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
    current_user: User = Depends(require_verified_email),
    db: Session = Depends(get_db),
) -> UndoSwipeOut:
    """
    Delete the current user's most recent swipe.

    Gated on email verification (GAPS #25), alongside swipe creation: undo is a
    write that can delete a match out from under the other party.

    If that swipe was a like that created a match, the match is deleted too.
    For demo user auto-matches, the demo's return-swipe is also removed so
    the discover queue is fully restored to its pre-swipe state.

    Returns the deleted swipe's target user so the frontend can push them
    back to the front of the discover stack.
    """
    # Ordered by id, not created_at: created_at is a Python-side default with
    # no server_default, so two swipes can share a timestamp (or arrive out of
    # order across replicas with skewed clocks).  The primary key is the only
    # monotonic record of insertion order.
    # Selected as plain columns rather than an ORM instance.  A concurrent
    # request that deletes this row and commits would expire a loaded Swipe
    # object, and the next attribute access would raise ObjectDeletedError
    # mid-request; a value tuple cannot go stale.
    last_swipe = (
        db.query(Swipe.id, Swipe.target_user_id, Swipe.direction)
        .filter(Swipe.user_id == current_user.id)
        .order_by(Swipe.id.desc())
        .first()
    )
    if last_swipe is None:
        raise HTTPException(status_code=404, detail="No swipes to undo.")

    swipe_id, target_user_id, direction = last_swipe

    target = db.query(User).filter(User.id == target_user_id).first()

    # Conditional delete: rowcount decides.  Two concurrent undos select the
    # same row, but only one deletes it — the loser gets a clean 404 instead of
    # a StaleDataError, and cannot go on to delete a second undo's match.
    if db.query(Swipe).filter(Swipe.id == swipe_id).delete(synchronize_session=False) == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="No swipes to undo.")

    if direction == SwipeDirection.like:
        u1, u2 = min(current_user.id, target_user_id), max(current_user.id, target_user_id)
        # Bulk delete so there is no loaded instance to go stale; messages hang
        # off the match by ON DELETE CASCADE, which applies either way.
        match_deleted = (
            db.query(Match)
            .filter(Match.user1_id == u1, Match.user2_id == u2)
            .delete(synchronize_session=False)
        )
        if match_deleted:
            # Also remove the other party's swipe (demo auto-match or a real mutual
            # like) so both users are fully restored to pre-swipe state.
            db.query(Swipe).filter(
                Swipe.user_id == target_user_id,
                Swipe.target_user_id == current_user.id,
            ).delete(synchronize_session=False)

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
