"""
Backfill auto-match tasks for existing likes on demo users.

Finds every Swipe(direction=like) whose target has a demo email and for
which no return-swipe from the demo user exists yet, then queues
auto_match_demo_user with a random staggered delay so matches trickle in
naturally rather than all arriving at once.

Usage (from repo root):
    python -m scripts.backfill_demo_matches            # queue tasks
    python -m scripts.backfill_demo_matches --dry-run  # preview only
"""

import argparse
import random
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal
from app.models.swipe import Swipe, SwipeDirection
from app.models.user import User
from app.tasks.auto_match import auto_match_demo_user

# Matches are spread over this window so they don't all pop at once.
_MAX_DELAY_S = 3600  # 60 minutes


def _find_eligible_swipes(db) -> list[tuple[int, int]]:
    """
    Return (user_id, demo_user_id) pairs that need an auto-match task.

    Eligible = real user liked a demo user AND the demo user has not yet
    swiped back (so we won't create a duplicate swipe/match).
    """
    # All likes on demo users
    likes = (
        db.query(Swipe.user_id, Swipe.target_user_id)
        .join(User, User.id == Swipe.target_user_id)
        .filter(
            Swipe.direction == SwipeDirection.like,
            User.email.like("demo%"),
        )
        .all()
    )

    # Ids of demo users that already have a return-swipe on the real user
    already_replied = set(
        db.query(Swipe.user_id, Swipe.target_user_id)
        .join(User, User.id == Swipe.user_id)
        .filter(User.email.like("demo%"))
        .all()
    )

    eligible = [
        (real_id, demo_id)
        for real_id, demo_id in likes
        if (demo_id, real_id) not in already_replied
    ]
    return eligible


def backfill(dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        eligible = _find_eligible_swipes(db)

        if not eligible:
            print("No eligible swipes found — nothing to backfill.")
            return

        print(f"Found {len(eligible)} swipe(s) eligible for backfill.")

        if dry_run:
            print("Dry-run mode — no tasks will be queued.\n")
            for real_id, demo_id in eligible:
                real_user = db.get(User, real_id)
                demo_user = db.get(User, demo_id)
                print(
                    f"  Would queue: real_user={real_user.email!r} "
                    f"→ demo={demo_user.email!r}"
                )
            return

        queued = 0
        for real_id, demo_id in eligible:
            delay = random.randint(0, _MAX_DELAY_S)
            auto_match_demo_user.apply_async(
                args=[real_id, demo_id],
                countdown=delay,
            )
            queued += 1
            demo_user = db.get(User, demo_id)
            print(
                f"  Queued: real_user_id={real_id} ← {demo_user.email!r} "
                f"(delay {delay}s / {delay // 60}m {delay % 60}s)"
            )

        print(f"\nQueued {queued} auto-match task(s).")

    except Exception as exc:
        print(f"Backfill failed: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill auto-match tasks for existing likes on demo users."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview eligible swipes without queuing any tasks.",
    )
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
