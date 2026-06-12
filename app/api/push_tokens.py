import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.push_token import PushToken
from app.models.user import User
from app.schemas.push_token import PushTokenIn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push-tokens", tags=["push-tokens"])


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
    """
    record = db.query(PushToken).filter(PushToken.token == body.token).first()
    if record is None:
        db.add(PushToken(user_id=current_user.id, token=body.token))
    elif record.user_id != current_user.id:
        record.user_id = current_user.id
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
