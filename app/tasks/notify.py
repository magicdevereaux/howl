"""
Notification fan-out tasks: email + Expo push for new messages and new matches.

Retry policy
------------
Both tasks bind (``bind=True``) and retry with exponential backoff plus full
jitter, bounded by ``_MAX_RETRIES``.  Only *transient* conditions retry:

* the Expo request never landed (transport error, 429, 5xx), or a ticket came
  back ``MessageRateExceeded`` / unreadable — see
  :class:`app.services.push_notifications.PushSendResult`;
* the email provider raised;
* the database connection dropped (``OperationalError`` / ``InterfaceError``).

Everything else is deliberately terminal.  A ``DeviceNotRegistered`` token is
deleted instead of retried, and ``MessageTooBig`` / ``InvalidCredentials``
tickets are logged and dropped — retrying a permanent verdict forever is as bad
as never retrying at all.

Duplicate delivery
------------------
``app/celery_app.py`` sets ``task_acks_late=True``, so a worker killed mid-task
gets the message redelivered and the task re-runs from the top.  There is no
dedup key here, so **a push or email notification can be delivered twice** in
that scenario.  That is an accepted trade-off: unlike ``generate_avatar`` a
duplicate notification costs nothing but a repeated banner, whereas a dropped
one is invisible to the user.

The retry path itself is narrowed so it does not add duplicates of its own: a
retry carries ``pending_tokens`` (only the tokens that still need delivering)
and ``email_sent`` (so a push-only retry does not re-send the email).

Push receipts
-------------
Only Expo *tickets* are consumed, not receipts.  Receipts carry the downstream
FCM/APNs verdict but are keyed by ticket id and only meaningful ~15 minutes
after the send, so harvesting them needs a ticket-id table plus a Beat job.
That is deferred; tickets already catch the case that matters here
(``DeviceNotRegistered`` tokens accumulating forever).
"""

import logging
import random
from datetime import UTC, datetime, timedelta

from celery.exceptions import Retry
from sqlalchemy import and_, or_
from sqlalchemy.exc import InterfaceError, OperationalError

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models.match import Match
from app.models.message import Message
from app.models.push_token import PushToken
from app.models.user import User
from app.services.email import send_message_notification
from app.services.push_notifications import PushSendResult, send_push_notifications

logger = logging.getLogger(__name__)

_ACTIVITY_WINDOW_MINUTES = 5

# Retry budget. 30s base with full jitter, doubling, capped at 15 minutes:
# roughly 30s / 1m / 2m / 4m / 8m of ceilings across five attempts.
_MAX_RETRIES = 5
_RETRY_BASE_S = 30
_RETRY_MAX_S = 15 * 60


def _push_tokens_for_user(db, user_id: int) -> list[str]:
    return [
        t for (t,) in db.query(PushToken.token).filter(PushToken.user_id == user_id).all()
    ]


def _retry_countdown(retries: int, floor_s: int | None = None) -> int:
    """
    Exponential backoff with full jitter, in seconds.

    Full jitter (uniform over ``[1, ceiling]``) rather than a fixed delay so that
    a burst of notifications failing against the same downstream does not
    thunder back in lockstep.  ``floor_s`` lets a server-supplied
    ``Retry-After`` raise the floor.
    """
    ceiling = min(_RETRY_MAX_S, _RETRY_BASE_S * (2**max(0, retries)))
    countdown = random.randint(1, ceiling)  # jitter only — not a security decision
    if floor_s:
        countdown = max(countdown, min(floor_s, _RETRY_MAX_S))
    return countdown


def _prune_expired_tokens(db, tokens: list[str]) -> int:
    """
    Delete push tokens Expo reported as ``DeviceNotRegistered``.

    Deleted by token rather than by user: ``push_tokens.token`` is unique and a
    dead token is dead for whoever holds it.
    """
    if not tokens:
        return 0
    try:
        deleted = (
            db.query(PushToken)
            .filter(PushToken.token.in_(tokens))
            .delete(synchronize_session=False)
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("notify: failed to prune %d dead push token(s)", len(tokens))
        return 0
    logger.info("notify: pruned %d dead push token(s)", deleted)
    return deleted


def _deliver_push(
    db,
    user_id: int,
    *,
    title: str,
    body: str,
    data: dict,
    only_tokens: list[str] | None = None,
) -> PushSendResult | None:
    """
    Push to a user's registered devices and reconcile the outcome.

    ``only_tokens`` restricts the send to a specific subset (used on retry) and
    is intersected with what is currently in the table, so a token pruned or
    rotated between attempts is not resurrected.  Returns ``None`` when there
    was nothing to send.
    """
    tokens = _push_tokens_for_user(db, user_id)
    if only_tokens is not None:
        wanted = set(only_tokens)
        tokens = [t for t in tokens if t in wanted]
    if not tokens:
        return None

    result = send_push_notifications(tokens, title=title, body=body, data=data)
    _prune_expired_tokens(db, result.expired_tokens)
    return result


def _retry(task, *, kwargs_update: dict, countdown: int, what: str) -> None:
    """
    Re-queue ``task`` with its original arguments plus ``kwargs_update``.

    Swallows ``MaxRetriesExceededError`` so exhausting the budget logs loudly
    instead of failing the task.  The ``Retry`` that ``task.retry()`` raises is
    *not* caught here — it has to escape all the way out of the task body, so
    every caller keeps an ``except Retry: raise`` ahead of its broad handler.
    """
    request = task.request
    logger.warning(
        "%s: retrying in %ds (attempt %d) — %s",
        task.name, countdown, request.retries + 1, what,
    )
    try:
        raise task.retry(
            args=request.args or (),
            kwargs={**(request.kwargs or {}), **kwargs_update},
            countdown=countdown,
        )
    except task.MaxRetriesExceededError:
        logger.error("%s: giving up after %d retries — %s", task.name, request.retries, what)


@celery_app.task(bind=True, max_retries=_MAX_RETRIES)
def notify_new_message(
    self,
    match_id: int,
    recipient_id: int,
    sender_id: int,
    *,
    email_sent: bool = False,
    pending_tokens: list[str] | None = None,
) -> None:
    """
    Send an email + push notification when a new chat message arrives — unless
    the recipient has been recently active in this conversation or has disabled
    email notifications.

    "Active" means they either read an incoming message or sent one of their
    own within the last _ACTIVITY_WINDOW_MINUTES minutes.  The check is
    re-evaluated at task execution time so that a recipient who opens the chat
    between the send and the Celery pickup does not receive a stale alert.  That
    also applies on retry: a recipient who has since opened the chat no longer
    needs the notification, so an outstanding retry is dropped.

    Message content is never included in the email for privacy.

    ``email_sent`` and ``pending_tokens`` are set by the retry path only — see
    the module docstring.
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

        email_failed = False
        if recipient.email_notifications and not email_sent:
            try:
                send_message_notification(
                    to_email=recipient.email,
                    sender_name=sender.name,
                    sender_animal=sender.animal,
                )
                email_sent = True
            except Exception as exc:
                # The provider is the only thing that can fail here, and provider
                # blips are transient — hand it to the retry path.
                email_failed = True
                logger.warning(
                    "notify_new_message: email failed for recipient %d: %s", recipient_id, exc
                )

        push = _deliver_push(
            db,
            recipient_id,
            title=sender.name or "New message",
            body="Sent you a message",
            data={"type": "message", "match_id": match_id},
            only_tokens=pending_tokens,
        )

        retry_tokens = push.retry_tokens if push else []
        if not email_failed and not retry_tokens:
            return

        reasons = []
        if email_failed:
            reasons.append("email delivery failed")
        if retry_tokens:
            reasons.append(f"{len(retry_tokens)} push token(s) undelivered")
        _retry(
            self,
            kwargs_update={"email_sent": email_sent, "pending_tokens": retry_tokens},
            countdown=_retry_countdown(
                self.request.retries, push.retry_after_s if push else None
            ),
            what=", ".join(reasons),
        )

    except Retry:
        # Our own retry signal — must reach the worker, not the handler below.
        raise
    except (OperationalError, InterfaceError) as exc:
        # Lost DB connection — nothing was decided, so try the whole task again.
        logger.warning("notify_new_message: database error for match=%s: %s", match_id, exc)
        _retry(
            self,
            kwargs_update={"email_sent": email_sent, "pending_tokens": pending_tokens},
            countdown=_retry_countdown(self.request.retries),
            what="database error",
        )
    except Exception as exc:
        logger.exception(
            "notify_new_message: unexpected error for match=%d recipient=%d: %s",
            match_id, recipient_id, exc,
        )
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=_MAX_RETRIES)
def notify_new_match(
    self,
    match_id: int,
    user_id: int,
    *,
    pending_tokens: list[str] | None = None,
) -> None:
    """
    Send a push notification to user_id telling them they have a new match.

    ``pending_tokens`` is set by the retry path only — see the module docstring.
    """
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

        push = _deliver_push(
            db,
            user_id,
            title="New match! 🎉",
            body=f"You matched with a {other_animal}",
            data={"type": "match", "match_id": match_id},
            only_tokens=pending_tokens,
        )

        if push and push.retry_tokens:
            _retry(
                self,
                kwargs_update={"pending_tokens": push.retry_tokens},
                countdown=_retry_countdown(self.request.retries, push.retry_after_s),
                what=f"{len(push.retry_tokens)} push token(s) undelivered",
            )

    except Retry:
        raise
    except (OperationalError, InterfaceError) as exc:
        logger.warning("notify_new_match: database error for match=%s: %s", match_id, exc)
        _retry(
            self,
            kwargs_update={"pending_tokens": pending_tokens},
            countdown=_retry_countdown(self.request.retries),
            what="database error",
        )
    except Exception as exc:
        logger.exception(
            "notify_new_match: unexpected error for match=%s user=%d: %s",
            match_id, user_id, exc,
        )
    finally:
        db.close()
