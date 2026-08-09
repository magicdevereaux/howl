import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.push_token import PushToken
from app.models.user import User
from app.schemas.push_token import PushTokenIn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push-tokens", tags=["push-tokens"])

# GAPS #57: without a ceiling, one account can register unbounded distinct
# tokens and every push to that user then queries and messages all of them
# (the token query in app/services/push_notifications.py has no LIMIT). 10 is
# generously above any real multi-device user's count while still bounding
# the worst case.
_MAX_TOKENS_PER_USER = 10


def _evict_oldest_beyond_cap(user_id: int, db: Session) -> None:
    """Keep at most `_MAX_TOKENS_PER_USER` rows for `user_id`, oldest first out."""
    keep_ids = (
        db.query(PushToken.id)
        .filter(PushToken.user_id == user_id)
        .order_by(PushToken.created_at.desc(), PushToken.id.desc())
        .limit(_MAX_TOKENS_PER_USER)
        .scalar_subquery()
    )
    evicted = (
        db.query(PushToken)
        .filter(PushToken.user_id == user_id, PushToken.id.notin_(keep_ids))
        .delete(synchronize_session=False)
    )
    if evicted:
        logger.info(
            "push_tokens: evicted %d token(s) for user %d over the %d-row cap",
            evicted, user_id, _MAX_TOKENS_PER_USER,
        )


@router.post("", status_code=204)
def register_push_token(
    body: PushTokenIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Register an Expo push token for the current user.

    Tokens are unique per device. If the device was previously registered to
    a different account (e.g. someone logged out and a new user logged in),
    reassign the token to the current user.

    GAPS #57: reassignment is authenticated-by-value, not by-session -- any
    account that learns another user's Expo token (a 22-character string, so
    this needs an out-of-band leak) can silently claim it and start receiving
    that person's notifications. A signed device attestation would close that
    properly but is a separate design decision and out of scope here; this at
    least makes every reassignment auditable via the warning log below. The
    format check (see PushTokenIn) and the per-user cap (`_evict_oldest_beyond_cap`)
    are the cheap, uncontroversial parts of this gap.
    """
    record = db.query(PushToken).filter(PushToken.token == body.token).first()
    if record is None:
        db.add(PushToken(user_id=current_user.id, token=body.token))
    elif record.user_id != current_user.id:
        logger.warning(
            "push_tokens: reassigning token from user %d to user %d",
            record.user_id, current_user.id,
        )
        record.user_id = current_user.id
        # Reassignment doesn't touch created_at by default, so a token that was
        # old under its previous owner would look "oldest" for its new owner
        # and could be evicted by the cap check below the moment it arrives.
        record.created_at = datetime.now(UTC)

    # The cap query below reads PushToken back through a fresh SELECT, so the
    # row just added/touched above must be visible to it first.
    db.flush()
    _evict_oldest_beyond_cap(current_user.id, db)

    db.commit()
    logger.info("push_tokens: registered token for user %d", current_user.id)


@router.delete("", status_code=204)
def unregister_push_token(
    body: PushTokenIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Remove a push token, e.g. on logout."""
    db.query(PushToken).filter(
        PushToken.token == body.token,
        PushToken.user_id == current_user.id,
    ).delete(synchronize_session=False)
    db.commit()
    logger.info("push_tokens: unregistered token for user %d", current_user.id)
