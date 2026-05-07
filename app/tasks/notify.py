import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models.message import Message
from app.models.user import User
from app.services.email import send_message_notification

logger = logging.getLogger(__name__)

_ACTIVITY_WINDOW_MINUTES = 5


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

        if not recipient.email_notifications:
            logger.debug(
                "notify_new_message: notifications disabled for user %d", recipient_id
            )
            return

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_ACTIVITY_WINDOW_MINUTES)

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

        send_message_notification(
            to_email=recipient.email,
            sender_name=sender.name,
            sender_animal=sender.animal,
        )

    except Exception as exc:
        logger.exception(
            "notify_new_message: unexpected error for match=%d recipient=%d: %s",
            match_id, recipient_id, exc,
        )
    finally:
        db.close()
