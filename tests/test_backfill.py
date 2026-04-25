"""Tests for scripts/backfill_demo_matches.py."""

import pytest

from app.models.swipe import Swipe, SwipeDirection
from app.models.user import AvatarStatus, User
from app.security import hash_password
from scripts.backfill_demo_matches import _find_eligible_swipes


def _make_user(db, *, email: str, **kwargs) -> User:
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        avatar_status=AvatarStatus.ready,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _swipe(db, *, from_id: int, to_id: int, direction: SwipeDirection) -> None:
    db.add(Swipe(user_id=from_id, target_user_id=to_id, direction=direction))
    db.commit()


# ---------------------------------------------------------------------------
# _find_eligible_swipes
# ---------------------------------------------------------------------------

def test_eligible_includes_unmatched_like_on_demo(db, test_user):
    demo = _make_user(db, email="demo1@howl.app")
    _swipe(db, from_id=test_user.id, to_id=demo.id, direction=SwipeDirection.like)

    result = _find_eligible_swipes(db)
    assert (test_user.id, demo.id) in result


def test_eligible_excludes_pass_on_demo(db, test_user):
    demo = _make_user(db, email="demo2@howl.app")
    _swipe(db, from_id=test_user.id, to_id=demo.id, direction=SwipeDirection.pass_)

    result = _find_eligible_swipes(db)
    assert (test_user.id, demo.id) not in result


def test_eligible_excludes_like_on_real_user(db, test_user):
    real = _make_user(db, email="real@howl.app")
    _swipe(db, from_id=test_user.id, to_id=real.id, direction=SwipeDirection.like)

    result = _find_eligible_swipes(db)
    assert (test_user.id, real.id) not in result


def test_eligible_excludes_already_replied(db, test_user):
    """If the demo already swiped back (either direction), skip."""
    demo = _make_user(db, email="demo3@howl.app")
    _swipe(db, from_id=test_user.id, to_id=demo.id, direction=SwipeDirection.like)
    _swipe(db, from_id=demo.id, to_id=test_user.id, direction=SwipeDirection.like)

    result = _find_eligible_swipes(db)
    assert (test_user.id, demo.id) not in result


def test_eligible_excludes_demo_that_passed(db, test_user):
    """Demo that already passed also counts as 'already replied'."""
    demo = _make_user(db, email="demo4@howl.app")
    _swipe(db, from_id=test_user.id, to_id=demo.id, direction=SwipeDirection.like)
    _swipe(db, from_id=demo.id, to_id=test_user.id, direction=SwipeDirection.pass_)

    result = _find_eligible_swipes(db)
    assert (test_user.id, demo.id) not in result


def test_eligible_multiple_users(db, test_user):
    demo_a = _make_user(db, email="demo5@howl.app")
    demo_b = _make_user(db, email="demo6@howl.app")
    other_real = _make_user(db, email="other@howl.app")

    _swipe(db, from_id=test_user.id, to_id=demo_a.id, direction=SwipeDirection.like)
    _swipe(db, from_id=test_user.id, to_id=demo_b.id, direction=SwipeDirection.like)
    _swipe(db, from_id=other_real.id, to_id=demo_a.id, direction=SwipeDirection.like)
    # demo_b already replied to other_real
    _swipe(db, from_id=demo_b.id, to_id=other_real.id, direction=SwipeDirection.like)

    result = _find_eligible_swipes(db)
    assert (test_user.id, demo_a.id) in result
    assert (test_user.id, demo_b.id) in result
    assert (other_real.id, demo_a.id) in result
    assert (other_real.id, demo_b.id) not in result


def test_empty_when_no_likes(db):
    assert _find_eligible_swipes(db) == []


# ---------------------------------------------------------------------------
# backfill() dry-run (no Celery queuing)
# ---------------------------------------------------------------------------

def test_dry_run_does_not_queue(db, test_user, monkeypatch, capsys):
    demo = _make_user(db, email="demo7@howl.app")
    _swipe(db, from_id=test_user.id, to_id=demo.id, direction=SwipeDirection.like)

    queued = []
    monkeypatch.setattr(
        "scripts.backfill_demo_matches.auto_match_demo_user.apply_async",
        lambda args, countdown: queued.append(args),
    )
    monkeypatch.setattr(
        "scripts.backfill_demo_matches.SessionLocal", lambda: db
    )

    from scripts.backfill_demo_matches import backfill
    backfill(dry_run=True)

    assert queued == []
    out = capsys.readouterr().out
    assert "dry-run" in out.lower()
    assert "demo7@howl.app" in out


def test_backfill_queues_tasks(db, test_user, monkeypatch):
    demo = _make_user(db, email="demo8@howl.app")
    _swipe(db, from_id=test_user.id, to_id=demo.id, direction=SwipeDirection.like)
    # Capture IDs before backfill() calls db.close(), which detaches ORM objects.
    real_id, demo_id = test_user.id, demo.id

    queued = []
    monkeypatch.setattr(
        "scripts.backfill_demo_matches.auto_match_demo_user.apply_async",
        lambda args, countdown: queued.append({"args": args, "countdown": countdown}),
    )
    monkeypatch.setattr(
        "scripts.backfill_demo_matches.SessionLocal", lambda: db
    )

    from scripts.backfill_demo_matches import backfill
    backfill(dry_run=False)

    assert len(queued) == 1
    assert queued[0]["args"] == [real_id, demo_id]
    assert 0 <= queued[0]["countdown"] <= 3600


def test_backfill_skips_already_replied(db, test_user, monkeypatch):
    demo = _make_user(db, email="demo9@howl.app")
    _swipe(db, from_id=test_user.id, to_id=demo.id, direction=SwipeDirection.like)
    _swipe(db, from_id=demo.id, to_id=test_user.id, direction=SwipeDirection.like)

    queued = []
    monkeypatch.setattr(
        "scripts.backfill_demo_matches.auto_match_demo_user.apply_async",
        lambda args, countdown: queued.append(args),
    )
    monkeypatch.setattr(
        "scripts.backfill_demo_matches.SessionLocal", lambda: db
    )

    from scripts.backfill_demo_matches import backfill
    backfill(dry_run=False)

    assert queued == []
