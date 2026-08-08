"""
Mark pre-existing accounts as email-verified, so enabling enforcement does not
retroactively lock out anyone who registered before it existed.

Background: GAPS #25. `require_verified_email` is now attached to the outbound
actions (swiping, message send, avatar generation). Enforcement is graduated —
an account keeps full access for `EMAIL_VERIFICATION_GRACE_PERIOD_HOURS` from
`created_at` — but every account older than that window would lose those actions
the moment enforcement shipped, having never been asked to verify. This script
grandfathers them in.

Usage (from the repo root):
    # dry run — the default; prints what it *would* change and writes nothing
    python -m scripts.backfill_email_verification

    # actually write
    python -m scripts.backfill_email_verification --apply

    # only accounts created before an explicit cutoff
    python -m scripts.backfill_email_verification --cutoff 2026-08-08T00:00:00Z --apply

Dry-run is the default and `--apply` is required, because this writes to the
production `users` table. Idempotent: it only touches rows where
`is_email_verified` is false, so a second run reports 0 changed.

Pick the cutoff to match the deploy that turned enforcement on. Accounts created
*after* it are the ones enforcement is actually for, and are left alone; they get
their normal grace window from `created_at`.
"""

import argparse
import os
import sys
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.user import User


def parse_cutoff(raw: str) -> datetime:
    """Parse an ISO-8601 cutoff into an aware UTC datetime.

    A naive input is *assumed* UTC rather than rejected: every timestamp in this
    app is stored as UTC, so silently reinterpreting it in the server's local
    zone would shift the cutoff by hours. Accepts a trailing "Z", which
    `fromisoformat` only learned to handle in 3.11+.
    """
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def backfill(db: Session, cutoff: datetime, apply_changes: bool) -> tuple[int, int]:
    """Verify every account created before `cutoff`.

    Returns ``(scanned, changed)`` where `scanned` is the number of accounts
    older than the cutoff and `changed` is how many were actually unverified —
    i.e. how many rows this run did (or in dry-run, would) update.

    Takes an explicit Session so this is callable from tests against the SQLite
    harness; `main` supplies the real one.
    """
    scanned = db.query(User).filter(User.created_at < cutoff).count()

    # `.is_(False)` rather than `== False` — ruff flags the latter (E712), and
    # this is also correct for a NULL-able boolean.
    pending_q = db.query(User).filter(
        User.created_at < cutoff,
        User.is_email_verified.is_(False),
    )
    changed = pending_q.count()

    if not apply_changes or changed == 0:
        return scanned, changed

    # One bulk UPDATE rather than loading and mutating instances: this runs
    # against the production users table and there is no per-row logic.
    # synchronize_session=False because nothing in this process holds those
    # instances, and the tz-aware bound cutoff cannot be evaluated in Python
    # against values SQLite hands back naive.
    result = db.execute(
        update(User)
        .where(User.created_at < cutoff, User.is_email_verified.is_(False))
        .values(is_email_verified=True),
        execution_options={"synchronize_session": False},
    )
    db.commit()

    # Trust the database's rowcount over the pre-flight COUNT: rows can be
    # inserted between the two statements.
    return scanned, result.rowcount if result.rowcount is not None else changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.backfill_email_verification",
        description=(
            "Mark accounts created before --cutoff as email-verified, so enabling "
            "verification enforcement does not lock out existing users."
        ),
    )
    parser.add_argument(
        "--cutoff",
        type=parse_cutoff,
        default=None,
        help=(
            "ISO-8601 datetime; only accounts with created_at < cutoff are touched. "
            "Naive values are treated as UTC. Defaults to now."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the changes. Without this the script is a dry run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly request a dry run (the default; accepted for clarity).",
    )
    args = parser.parse_args(argv)

    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive.")

    cutoff = args.cutoff or datetime.now(UTC)
    apply_changes = args.apply

    mode = "APPLY" if apply_changes else "DRY RUN"
    print(f"[{mode}] cutoff = {cutoff.isoformat()}")

    db = SessionLocal()
    try:
        scanned, changed = backfill(db, cutoff, apply_changes)
    except Exception as exc:
        db.rollback()
        print(f"Backfill failed: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()

    print(f"  Accounts created before cutoff: {scanned}")
    if apply_changes:
        print(f"  Marked verified:                {changed}")
        if changed == 0:
            print("  Nothing to do — already consistent.")
    else:
        print(f"  Would mark verified:            {changed}")
        print("  No changes written. Re-run with --apply to commit them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
