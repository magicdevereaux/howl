"""GAPS-ROUND-2 #43 — enqueueing must fail open, like every other Redis dependency.

The bug being pinned: `POST /api/matches/{id}/messages` commits the message and
*then* enqueues the notification.  With the broker unreachable that enqueue blocked
for ~109 seconds and raised, so the endpoint returned 500 for a message that was
already in the database — and the web client, seeing a failure, re-sent it.

These tests assert the endpoint's behaviour, not the helper's, because the helper
returning None is not the thing that matters; the request still succeeding is.
"""

import pytest

from app.models.match import Match
from app.models.message import Message
from app.models.user import AvatarStatus, User
from app.security import create_access_token, hash_password
from app.services import task_queue


class _DeadBroker(Exception):
    """Stands in for kombu's OperationalError / OSError / RuntimeError family."""


class _FakeTask:
    name = "app.tasks.fake"

    def __init__(self, exc: Exception | None = None):
        self.exc = exc
        self.calls: list[tuple] = []

    def delay(self, *args):
        if self.exc:
            raise self.exc
        self.calls.append(args)
        return type("R", (), {"id": "abc-123"})()

    def apply_async(self, args=None, countdown=None):
        if self.exc:
            raise self.exc
        self.calls.append((tuple(args or ()), countdown))
        return type("R", (), {"id": "abc-123"})()


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------

def test_enqueue_returns_task_id_on_success():
    task = _FakeTask()
    assert task_queue.enqueue(task, 1, 2) == "abc-123"
    assert task.calls == [(1, 2)]


def test_enqueue_uses_apply_async_when_a_countdown_is_given():
    task = _FakeTask()
    task_queue.enqueue(task, 7, countdown=30)
    assert task.calls == [((7,), 30)]


@pytest.mark.parametrize(
    "exc",
    [_DeadBroker("connection refused"), OSError("no route to host"), RuntimeError("retry limit")],
)
def test_enqueue_swallows_broker_failures(exc, caplog):
    """Any connect/publish failure returns None instead of propagating."""
    assert task_queue.enqueue(_FakeTask(exc), 1) is None
    assert "could not enqueue" in caplog.text


# ---------------------------------------------------------------------------
# The behaviour that actually matters: the write survives a dead broker
# ---------------------------------------------------------------------------

def _make_match(db) -> tuple[User, User, Match]:
    a = User(
        email="a@howl.app", password_hash=hash_password("hunter2secure"),
        avatar_status=AvatarStatus.ready, animal="Wolf",
    )
    b = User(
        email="b@howl.app", password_hash=hash_password("hunter2secure"),
        avatar_status=AvatarStatus.ready, animal="Fox",
    )
    db.add_all([a, b])
    db.commit()
    lo, hi = sorted([a.id, b.id])
    match = Match(user1_id=lo, user2_id=hi)
    db.add(match)
    db.commit()
    db.refresh(match)
    return a, b, match


def test_send_message_succeeds_when_the_broker_is_down(client, db, monkeypatch):
    """The message is committed, so the request must not 500 (#43).

    Before the fix this returned 500 after a ~109s block, and the client re-sent —
    producing two copies of a message the server had already stored.
    """
    sender, _recipient, match = _make_match(db)
    headers = {"Cookie": f"access_token={create_access_token(sender.id)}"}

    def dead_delay(*_a, **_kw):
        raise _DeadBroker("Error 111 connecting to localhost:6379. Connection refused.")

    monkeypatch.setattr("app.tasks.notify.notify_new_message.delay", dead_delay)

    res = client.post(
        f"/api/matches/{match.id}/messages",
        json={"content": "hello from the other side"},
        headers=headers,
    )

    assert res.status_code == 201, res.text
    assert db.query(Message).filter(Message.match_id == match.id).count() == 1


def test_regenerate_avatar_succeeds_when_the_broker_is_down(client, db, monkeypatch):
    """The avatar row is reset and committed before the enqueue, same shape as above."""
    user = User(
        email="regen@howl.app", password_hash=hash_password("hunter2secure"),
        bio="I like long walks and short deadlines.", avatar_status=AvatarStatus.ready,
        animal="Otter", avatar_url="/avatars/old.png", is_email_verified=True,
    )
    db.add(user)
    db.commit()
    headers = {"Cookie": f"access_token={create_access_token(user.id)}"}

    monkeypatch.setattr(
        "app.tasks.avatar.generate_avatar.delay",
        lambda *_a, **_kw: (_ for _ in ()).throw(_DeadBroker("broker down")),
    )

    res = client.post("/api/avatar/regenerate", headers=headers)

    assert res.status_code == 200, res.text
    db.refresh(user)
    assert user.avatar_status == AvatarStatus.pending


# ---------------------------------------------------------------------------
# The conftest fixture (#61)
# ---------------------------------------------------------------------------

def test_autouse_fixture_records_enqueues_without_a_broker(celery_enqueues, client, db):
    """A test that never patches `.delay` must still not reach the real broker.

    This is the whole point of the fixture: before it existed, a new test file that
    posted a message hit the real Redis, and in CI (no Redis service) that cost
    108.8 seconds and a poisoned result backend for the rest of the process.
    """
    sender, _recipient, match = _make_match(db)
    headers = {"Cookie": f"access_token={create_access_token(sender.id)}"}

    res = client.post(
        f"/api/matches/{match.id}/messages",
        json={"content": "unpatched"},
        headers=headers,
    )

    assert res.status_code == 201
    names = [name for name, _args, _kw in celery_enqueues]
    assert "app.tasks.notify.notify_new_message" in names
