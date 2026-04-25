"""Tests for the auto_match_demo_user Celery task and its dispatch from POST /api/swipes."""

import pytest

from app.models.match import Match
from app.models.swipe import Swipe, SwipeDirection
from app.models.user import AvatarStatus, User
from app.security import hash_password
from app.tasks.auto_match import auto_match_demo_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, *, email: str, avatar_status: AvatarStatus = AvatarStatus.ready, **kwargs) -> User:
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        avatar_status=avatar_status,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_swipe(db, *, user_id: int, target_user_id: int, direction: SwipeDirection) -> Swipe:
    swipe = Swipe(user_id=user_id, target_user_id=target_user_id, direction=direction)
    db.add(swipe)
    db.commit()
    db.refresh(swipe)
    return swipe


# ---------------------------------------------------------------------------
# Task unit tests
#
# The task opens its own SessionLocal() which would try Postgres.
# We monkeypatch SessionLocal to return the test SQLite session instead.
# ---------------------------------------------------------------------------

@pytest.fixture()
def patched_session(db, monkeypatch):
    """Make the task's SessionLocal() return the test SQLite session."""
    monkeypatch.setattr("app.tasks.auto_match.SessionLocal", lambda: db)
    return db


def test_task_creates_like_and_match(patched_session, test_user, monkeypatch):
    """90%-path: when random() < 0.9 the demo user likes back and a Match is created."""
    db = patched_session
    demo = _make_user(db, email="demo1@howl.app", animal="fox")
    _make_swipe(db, user_id=test_user.id, target_user_id=demo.id, direction=SwipeDirection.like)
    # Capture IDs before task runs — task calls db.close() which detaches ORM objects.
    real_id, demo_id = test_user.id, demo.id

    monkeypatch.setattr("app.tasks.auto_match.random.random", lambda: 0.5)

    auto_match_demo_user(real_id, demo_id)

    swipe = db.query(Swipe).filter(Swipe.user_id == demo_id, Swipe.target_user_id == real_id).first()
    assert swipe is not None
    assert swipe.direction == SwipeDirection.like

    match = db.query(Match).first()
    assert match is not None
    assert min(real_id, demo_id) == match.user1_id
    assert max(real_id, demo_id) == match.user2_id


def test_task_creates_pass_no_match(patched_session, test_user, monkeypatch):
    """10%-path: when random() >= 0.9 the demo user passes and no Match is created."""
    db = patched_session
    demo = _make_user(db, email="demo2@howl.app", animal="bear")
    _make_swipe(db, user_id=test_user.id, target_user_id=demo.id, direction=SwipeDirection.like)
    real_id, demo_id = test_user.id, demo.id

    monkeypatch.setattr("app.tasks.auto_match.random.random", lambda: 0.95)

    auto_match_demo_user(real_id, demo_id)

    swipe = db.query(Swipe).filter(Swipe.user_id == demo_id, Swipe.target_user_id == real_id).first()
    assert swipe is not None
    assert swipe.direction == SwipeDirection.pass_

    assert db.query(Match).count() == 0


def test_task_skips_non_demo_user(patched_session, test_user):
    """Task bails if demo_user_id doesn't have a demo email."""
    db = patched_session
    real_other = _make_user(db, email="notademo@howl.app", animal="owl")
    _make_swipe(db, user_id=test_user.id, target_user_id=real_other.id, direction=SwipeDirection.like)

    auto_match_demo_user(test_user.id, real_other.id)

    assert db.query(Swipe).filter(Swipe.user_id == real_other.id).count() == 0
    assert db.query(Match).count() == 0


def test_task_skips_missing_real_user(patched_session):
    db = patched_session
    demo = _make_user(db, email="demo3@howl.app")

    auto_match_demo_user(99999, demo.id)

    assert db.query(Swipe).filter(Swipe.user_id == demo.id).count() == 0


def test_task_skips_missing_demo_user(patched_session, test_user):
    auto_match_demo_user(test_user.id, 99999)

    assert patched_session.query(Swipe).count() == 0


def test_task_skips_if_real_user_no_longer_likes(patched_session, test_user):
    """If the original like swipe is absent (e.g. pass swipe only), task is a no-op."""
    db = patched_session
    demo = _make_user(db, email="demo4@howl.app", animal="deer")
    # No like swipe from test_user → demo

    auto_match_demo_user(test_user.id, demo.id)

    assert db.query(Swipe).filter(Swipe.user_id == demo.id).count() == 0


def test_task_idempotent_if_demo_already_swiped(patched_session, test_user, monkeypatch):
    """Task is a no-op if the demo user already has a swipe on the real user."""
    db = patched_session
    demo = _make_user(db, email="demo5@howl.app", animal="wolf")
    _make_swipe(db, user_id=test_user.id, target_user_id=demo.id, direction=SwipeDirection.like)
    _make_swipe(db, user_id=demo.id, target_user_id=test_user.id, direction=SwipeDirection.like)

    called = []
    monkeypatch.setattr("app.tasks.auto_match.random.random", lambda: (called.append(1), 0.5)[1])

    auto_match_demo_user(test_user.id, demo.id)

    # random.random was never called — task exited before the coin flip
    assert len(called) == 0
    assert db.query(Swipe).filter(Swipe.user_id == demo.id, Swipe.target_user_id == test_user.id).count() == 1


def test_task_handles_real_user_pass_on_demo(patched_session, test_user):
    """A pass swipe from the real user satisfies no 'like' check — no auto-reply."""
    db = patched_session
    demo = _make_user(db, email="demo6@howl.app")
    _make_swipe(db, user_id=test_user.id, target_user_id=demo.id, direction=SwipeDirection.pass_)

    auto_match_demo_user(test_user.id, demo.id)

    assert db.query(Swipe).filter(Swipe.user_id == demo.id).count() == 0


# ---------------------------------------------------------------------------
# Integration: POST /api/swipes dispatches task for demo targets
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_apply_async(monkeypatch):
    """Capture apply_async calls without touching Celery/Redis."""
    calls = []
    monkeypatch.setattr(
        "app.api.swipes.auto_match_demo_user.apply_async",
        lambda args, countdown: calls.append({"args": args, "countdown": countdown}),
    )
    return calls


def test_swipe_like_on_demo_queues_task(client, db, auth_headers, test_user, mock_apply_async):
    demo = _make_user(db, email="demo7@howl.app", animal="fox")

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": demo.id, "direction": "like"},
    )
    assert res.status_code == 200
    assert len(mock_apply_async) == 1
    call = mock_apply_async[0]
    assert call["args"] == [test_user.id, demo.id]
    assert call["countdown"] == 30  # _DEMO_REPLY_DELAY_S


def test_swipe_pass_on_demo_does_not_queue_task(client, db, auth_headers, mock_apply_async):
    demo = _make_user(db, email="demo8@howl.app", animal="bear")

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": demo.id, "direction": "pass"},
    )
    assert res.status_code == 200
    assert len(mock_apply_async) == 0


def test_swipe_like_on_non_demo_does_not_queue_task(client, db, auth_headers, mock_apply_async):
    real_other = _make_user(db, email="real@howl.app", animal="owl")

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": real_other.id, "direction": "like"},
    )
    assert res.status_code == 200
    assert len(mock_apply_async) == 0
