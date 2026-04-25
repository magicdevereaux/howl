import logging
import random

from sqlalchemy.exc import IntegrityError

from app.celery_app import celery_app
from app.db import SessionLocal
from app.models.match import Match
from app.models.swipe import Swipe, SwipeDirection
from app.models.user import User

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def auto_match_demo_user(self, user_id: int, demo_user_id: int) -> None:
    """
    Probabilistic auto-like from a demo user back to a real user who liked them.

    Flow:
      1. Verify both users exist and demo_user_id is actually a demo account.
      2. Confirm the real user still has a 'like' swipe on the demo user
         (they may have been deleted or the task queued erroneously).
      3. Skip if the demo user already swiped on the real user (idempotent).
      4. 90% chance: demo likes back → creates a Match row.
         10% chance: demo passes → only a pass Swipe is written.
    """
    db = SessionLocal()
    try:
        demo_user = db.get(User, demo_user_id)
        real_user = db.get(User, user_id)

        if demo_user is None or real_user is None:
            logger.warning(
                "auto_match: user_id=%d or demo_user_id=%d not found — skipping",
                user_id, demo_user_id,
            )
            return

        if not demo_user.email.startswith("demo"):
            logger.warning(
                "auto_match: demo_user_id=%d (%r) is not a demo account — skipping",
                demo_user_id, demo_user.email,
            )
            return

        # Confirm real user still has a like on the demo user
        original_like = (
            db.query(Swipe)
            .filter(
                Swipe.user_id == user_id,
                Swipe.target_user_id == demo_user_id,
                Swipe.direction == SwipeDirection.like,
            )
            .first()
        )
        if original_like is None:
            logger.info(
                "auto_match: real user %d no longer has a like on demo user %d — skipping",
                user_id, demo_user_id,
            )
            return

        # Idempotency: skip if demo already swiped on the real user
        already_swiped = (
            db.query(Swipe)
            .filter(Swipe.user_id == demo_user_id, Swipe.target_user_id == user_id)
            .first()
        )
        if already_swiped is not None:
            logger.info(
                "auto_match: demo user %d already swiped on real user %d — skipping",
                demo_user_id, user_id,
            )
            return

        # 90% like, 10% pass
        direction = SwipeDirection.like if random.random() < 0.9 else SwipeDirection.pass_
        logger.info(
            "auto_match: demo user %d → real user %d: %s",
            demo_user_id, user_id, direction.value,
        )

        swipe = Swipe(user_id=demo_user_id, target_user_id=user_id, direction=direction)
        db.add(swipe)
        db.flush()

        if direction == SwipeDirection.like:
            u1 = min(user_id, demo_user_id)
            u2 = max(user_id, demo_user_id)
            match = Match(user1_id=u1, user2_id=u2)
            db.add(match)

        db.commit()
        logger.info(
            "auto_match: committed — demo=%d real=%d direction=%s matched=%s",
            demo_user_id, user_id, direction.value, direction == SwipeDirection.like,
        )

    except IntegrityError:
        db.rollback()
        logger.warning(
            "auto_match: IntegrityError for demo=%d real=%d — match or swipe already exists",
            demo_user_id, user_id,
        )

    except Exception as exc:
        db.rollback()
        logger.exception(
            "auto_match: unexpected error for demo=%d real=%d: %s",
            demo_user_id, user_id, exc,
        )
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error(
                "auto_match: max retries exceeded for demo=%d real=%d",
                demo_user_id, user_id,
            )

    finally:
        db.close()
