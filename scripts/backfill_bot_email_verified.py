"""
One-time script: set is_email_verified=True for every bot user.

Usage (from repo root):
    python -m scripts.backfill_bot_email_verified
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal
from app.models.user import User


def run() -> None:
    db = SessionLocal()
    try:
        updated = (
            db.query(User)
            .filter(User.is_bot == True, User.is_email_verified == False)  # noqa: E712
            .update({"is_email_verified": True}, synchronize_session=False)
        )
        db.commit()
        print(f"Updated {updated} bot user(s) → is_email_verified=True.")
    except Exception as exc:
        db.rollback()
        print(f"Backfill failed: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
