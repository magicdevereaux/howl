import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.match import Match
from app.models.message import Message
from app.models.swipe import Swipe
from app.models.user import User
from app.schemas.chat import MessageIn, MessageOut, MessagePageOut, UnreadCountOut
from app.tasks.notify import notify_new_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/matches", tags=["chat"])

_RATE_LIMIT_MAX = 10       # messages per window
_RATE_LIMIT_WINDOW_S = 60  # seconds
_PAGE_SIZE = 50            # messages returned per request


def _require_match_member(match_id: int, user_id: int, db: Session) -> Match:
    """Return the Match or raise 404/403."""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found.")
    if user_id not in (match.user1_id, match.user2_id):
        raise HTTPException(status_code=403, detail="Not part of this match.")
    return match


def _to_out(msg: Message, current_user_id: int) -> MessageOut:
    return MessageOut(
        id=msg.id,
        sender_id=msg.sender_id,
        # Hide content for soft-deleted messages so neither party sees the original text
        content=None if msg.deleted_at else msg.content,
        created_at=msg.created_at,
        read_at=msg.read_at,
        deleted_at=msg.deleted_at,
        is_mine=(msg.sender_id == current_user_id),
    )


@router.delete("/{match_id}", status_code=204)
def unmatch(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    Remove a match and its conversation without blocking either user.

    Deletes the match (messages cascade), then removes both swipe records so
    both parties can rediscover each other organically.
    """
    match = _require_match_member(match_id, current_user.id, db)
    other_id = match.user2_id if match.user1_id == current_user.id else match.user1_id

    db.delete(match)  # messages cascade via FK

    # Remove both swipes so each user reappears in the other's discover queue
    db.query(Swipe).filter(
        ((Swipe.user_id == current_user.id) & (Swipe.target_user_id == other_id)) |
        ((Swipe.user_id == other_id) & (Swipe.target_user_id == current_user.id))
    ).delete(synchronize_session=False)

    db.commit()
    logger.info("chat: user %d unmatched match %d", current_user.id, match_id)


@router.delete("/{match_id}/messages/{message_id}", response_model=MessageOut, status_code=200)
def delete_message(
    match_id: int,
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    """Soft-delete a sent message. Only the original sender may delete it."""
    _require_match_member(match_id, current_user.id, db)

    msg = db.query(Message).filter(
        Message.id == message_id,
        Message.match_id == match_id,
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found.")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot delete a message you did not send.")
    if msg.deleted_at:
        return _to_out(msg, current_user.id)  # idempotent

    msg.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(msg)
    logger.info("chat: user %d soft-deleted message %d", current_user.id, message_id)
    return _to_out(msg, current_user.id)


@router.get("/{match_id}/messages", response_model=MessagePageOut)
def get_messages(
    match_id: int,
    before_id: int | None = Query(default=None, description="Cursor: return messages with id < before_id"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessagePageOut:
    """
    Fetch paginated conversation history and mark incoming messages as read.

    Returns the _PAGE_SIZE most recent messages by default.  Pass
    ``before_id`` to page backward (load older messages).  The response
    includes ``has_more`` so the client knows whether a previous page exists.
    """
    _require_match_member(match_id, current_user.id, db)

    q = db.query(Message).filter(Message.match_id == match_id)
    if before_id is not None:
        q = q.filter(Message.id < before_id)

    # Fetch newest-first so LIMIT gives us the _PAGE_SIZE most recent rows;
    # then reverse to restore chronological (ascending) display order.
    raw = q.order_by(Message.id.desc()).limit(_PAGE_SIZE + 1).all()
    has_more = len(raw) > _PAGE_SIZE
    if has_more:
        raw = raw[:_PAGE_SIZE]
    messages = list(reversed(raw))

    now = datetime.now(timezone.utc)
    marked = False
    for msg in messages:
        if msg.sender_id != current_user.id and msg.read_at is None:
            msg.read_at = now
            marked = True
    if marked:
        db.commit()

    return MessagePageOut(
        messages=[_to_out(msg, current_user.id) for msg in messages],
        has_more=has_more,
    )


@router.post("/{match_id}/messages", response_model=MessageOut, status_code=201)
def send_message(
    match_id: int,
    body: MessageIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageOut:
    """Send a message to a match. Rate-limited to 10 per 60 seconds."""
    match = _require_match_member(match_id, current_user.id, db)

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_RATE_LIMIT_WINDOW_S)
    recent = (
        db.query(Message)
        .filter(
            Message.match_id == match_id,
            Message.sender_id == current_user.id,
            Message.created_at >= cutoff,
        )
        .count()
    )
    if recent >= _RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Sending too fast. Please wait a moment.")

    msg = Message(
        match_id=match_id,
        sender_id=current_user.id,
        content=body.content,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    logger.info("chat: user=%d sent message to match=%d", current_user.id, match_id)

    # Notify the other participant (fire-and-forget; task handles all skip logic)
    recipient_id = match.user2_id if match.user1_id == current_user.id else match.user1_id
    notify_new_message.delay(match_id, recipient_id, current_user.id)

    return _to_out(msg, current_user.id)


@router.get("/{match_id}/unread-count", response_model=UnreadCountOut)
def unread_count(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnreadCountOut:
    """Count unread messages sent by the other user."""
    _require_match_member(match_id, current_user.id, db)

    count = (
        db.query(Message)
        .filter(
            Message.match_id == match_id,
            Message.sender_id != current_user.id,
            Message.read_at.is_(None),
        )
        .count()
    )
    return UnreadCountOut(count=count)
