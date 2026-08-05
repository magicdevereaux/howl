import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models.match import Match
from app.models.message import Message
from app.models.push_token import PushToken
from app.models.user import User
from app.services.email import send_message_notification
from app.services.push_notifications import send_push_notifications

logger = logging.getLogger(__name__)

_ACTIVITY_WINDOW_MINUTES = 5


def _push_tokens_for_user(db, user_id: int) -> list[str]:
    return [
        t for (t,) in db.query(PushToken.token).filter(PushToken.user_id == user_id).all()
    ]


@celery_app.task
def notify_new_message(match_id: int, recipient_id: int, sender_id: int) -> None:
    """
    Send an email notification when a new chat message arrives — unless the
    recipient has been recently active in this conversation or has disabled
    email notifications.

    "Active" means they either read an incoming message or sent one of their
    own within the last _ACTIVITY_WINDOW_MINUTES minutes.  The check is
    re-evaluated at task execution time so that a recipient who opens the chat
    between the send and the Celery pickup does not receive a stale alert.

    Message content is never included in the email for privacy.
    """
    db = SessionLocal()
    try:
        recipient = db.get(User, recipient_id)
        sender = db.get(User, sender_id)

        if not recipient or not sender:
            logger.warning(
                "notify_new_message: missing user(s) — recipient=%d sender=%d",
                recipient_id, sender_id,
            )
            return

        cutoff = datetime.now(UTC) - timedelta(minutes=_ACTIVITY_WINDOW_MINUTES)

        recently_active = (
            db.query(Message)
            .filter(
                Message.match_id == match_id,
                or_(
                    # They read an incoming message recently (chat was open)
                    and_(
                        Message.sender_id != recipient_id,
                        Message.read_at >= cutoff,
                    ),
                    # They sent a message recently (definitely in the chat)
                    and_(
                        Message.sender_id == recipient_id,
                        Message.created_at >= cutoff,
                    ),
                ),
            )
            .first()
        )

        if recently_active:
            logger.debug(
                "notify_new_message: recipient %d is active in match %d — skipping",
                recipient_id, match_id,
            )
            return

        if recipient.email_notifications:
            send_message_notification(
                to_email=recipient.email,
                sender_name=sender.name,
                sender_animal=sender.animal,
            )

        tokens = _push_tokens_for_user(db, recipient_id)
        send_push_notifications(
            tokens,
            title=sender.name or "New message",
            body="Sent you a message",
            data={"type": "message", "match_id": match_id},
        )

    except Exception as exc:
        logger.exception(
            "notify_new_message: unexpected error for match=%d recipient=%d: %s",
            match_id, recipient_id, exc,
        )
    finally:
        db.close()


@celery_app.task
def notify_new_match(match_id: int, user_id: int) -> None:
    """Send a push notification to user_id telling them they have a new match."""
    db = SessionLocal()
    try:
        match = db.get(Match, match_id)
        user = db.get(User, user_id)
        if not match or not user:
            logger.warning(
                "notify_new_match: missing match=%s or user=%d", match_id, user_id
            )
            return

        other_id = match.user2_id if match.user1_id == user_id else match.user1_id
        other = db.get(User, other_id)
        other_animal = (other.animal if other else None) or "spirit animal"

        tokens = _push_tokens_for_user(db, user_id)
        send_push_notifications(
            tokens,
            title="New match! 🎉",
            body=f"You matched with a {other_animal}",
            data={"type": "match", "match_id": match_id},
        )
    except Exception as exc:
        logger.exception(
            "notify_new_match: unexpected error for match=%s user=%d: %s",
            match_id, user_id, exc,
        )
    finally:
        db.close()
