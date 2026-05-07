"""Tests for the notify_new_message Celery task and the email_notifications preference."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.match import Match
from app.models.message import Message
from app.models.user import AvatarStatus, User
from app.security import hash_password
from app.tasks.notify import notify_new_message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, *, email: str, email_notifications: bool = True, **kwargs) -> User:
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        avatar_status=AvatarStatus.ready,
        email_notifications=email_notifications,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_match(db, a: User, b: User) -> Match:
    m = Match(user1_id=min(a.id, b.id), user2_id=max(a.id, b.id))
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _make_message(db, *, match_id: int, sender_id: int, read_at=None, created_at=None) -> Message:
    kwargs = {}
    if created_at is not None:
        kwargs["created_at"] = created_at
    msg = Message(match_id=match_id, sender_id=sender_id, content="hi", read_at=read_at, **kwargs)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@pytest.fixture()
def patched_db(db, monkeypatch):
    """Wire the task's SessionLocal() to the test SQLite session."""
    monkeypatch.setattr("app.tasks.notify.SessionLocal", lambda: db)
    return db


# ---------------------------------------------------------------------------
# Task: skip conditions
# ---------------------------------------------------------------------------

def test_skips_when_notifications_disabled(patched_db, monkeypatch):
    db = patched_db
    sender = _make_user(db, email="sender@howl.app", name="Luna", animal="fox")
    recipient = _make_user(db, email="recipient@howl.app", email_notifications=False)
    m = _make_match(db, sender, recipient)
    sent = []
    monkeypatch.setattr("app.tasks.notify.send_message_notification", lambda **kw: sent.append(kw))

    notify_new_message(m.id, recipient.id, sender.id)

    assert sent == []


def test_skips_when_recipient_read_message_recently(patched_db, monkeypatch):
    """Recipient read an incoming message within the last 5 minutes → active → no email."""
    db = patched_db
    sender = _make_user(db, email="sender2@howl.app", name="Fox", animal="fox")
    recipient = _make_user(db, email="recipient2@howl.app")
    m = _make_match(db, sender, recipient)

    recent_read = datetime.now(timezone.utc) - timedelta(minutes=2)
    _make_message(db, match_id=m.id, sender_id=sender.id, read_at=recent_read)

    sent = []
    monkeypatch.setattr("app.tasks.notify.send_message_notification", lambda **kw: sent.append(kw))

    notify_new_message(m.id, recipient.id, sender.id)

    assert sent == []


def test_skips_when_recipient_sent_message_recently(patched_db, monkeypatch):
    """Recipient sent a message within the last 5 minutes → still typing → no email."""
    db = patched_db
    sender = _make_user(db, email="sender3@howl.app", name="Wolf", animal="wolf")
    recipient = _make_user(db, email="recipient3@howl.app")
    m = _make_match(db, sender, recipient)

    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    _make_message(db, match_id=m.id, sender_id=recipient.id, created_at=recent)

    sent = []
    monkeypatch.setattr("app.tasks.notify.send_message_notification", lambda **kw: sent.append(kw))

    notify_new_message(m.id, recipient.id, sender.id)

    assert sent == []


def test_skips_when_missing_recipient(patched_db, monkeypatch):
    db = patched_db
    sender = _make_user(db, email="sender4@howl.app")
    m = _make_match(db, sender, sender)  # degenerate; just need a match_id
    sent = []
    monkeypatch.setattr("app.tasks.notify.send_message_notification", lambda **kw: sent.append(kw))

    notify_new_message(m.id, 99999, sender.id)

    assert sent == []


# ---------------------------------------------------------------------------
# Task: send conditions
# ---------------------------------------------------------------------------

def test_sends_when_recipient_inactive(patched_db, monkeypatch):
    """Recipient has no recent activity → notification should fire."""
    db = patched_db
    sender = _make_user(db, email="sender5@howl.app", name="Iris", animal="owl")
    recipient = _make_user(db, email="recipient5@howl.app")
    m = _make_match(db, sender, recipient)

    # Old message, read a long time ago — not recent activity
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    _make_message(db, match_id=m.id, sender_id=sender.id, read_at=old)

    sent = []
    monkeypatch.setattr(
        "app.tasks.notify.send_message_notification",
        lambda to_email, sender_name, sender_animal: sent.append({
            "to": to_email, "name": sender_name, "animal": sender_animal,
        }),
    )

    notify_new_message(m.id, recipient.id, sender.id)

    assert len(sent) == 1
    assert sent[0]["to"] == recipient.email
    assert sent[0]["name"] == "Iris"
    assert sent[0]["animal"] == "owl"


def test_sends_when_no_prior_messages(patched_db, monkeypatch):
    """First message in the conversation — recipient has had no activity."""
    db = patched_db
    sender = _make_user(db, email="sender6@howl.app", name="Sam", animal="bear")
    recipient = _make_user(db, email="recipient6@howl.app")
    m = _make_match(db, sender, recipient)

    sent = []
    monkeypatch.setattr(
        "app.tasks.notify.send_message_notification",
        lambda to_email, sender_name, sender_animal: sent.append(True),
    )

    notify_new_message(m.id, recipient.id, sender.id)

    assert len(sent) == 1


def test_notification_omits_message_content(patched_db, monkeypatch):
    """Verify the email function signature never receives message content."""
    db = patched_db
    sender = _make_user(db, email="sender7@howl.app", name="Alex", animal="deer")
    recipient = _make_user(db, email="recipient7@howl.app")
    m = _make_match(db, sender, recipient)

    captured = {}
    def fake_email(to_email, sender_name, sender_animal):
        captured.update({"to": to_email, "name": sender_name, "animal": sender_animal})
    monkeypatch.setattr("app.tasks.notify.send_message_notification", fake_email)

    notify_new_message(m.id, recipient.id, sender.id)

    # Only these three keys — no "content" or "message" key
    assert set(captured.keys()) == {"to", "name", "animal"}


# ---------------------------------------------------------------------------
# email_notifications preference via API
# ---------------------------------------------------------------------------

def test_email_notifications_default_true(client, auth_headers):
    res = client.get("/api/profile/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["email_notifications"] is True


def test_patch_email_notifications_off(client, auth_headers):
    res = client.patch(
        "/api/profile/me",
        headers=auth_headers,
        json={"email_notifications": False},
    )
    assert res.status_code == 200
    assert res.json()["email_notifications"] is False


def test_patch_email_notifications_on(client, db, auth_headers, test_user):
    test_user.email_notifications = False
    db.commit()

    res = client.patch(
        "/api/profile/me",
        headers=auth_headers,
        json={"email_notifications": True},
    )
    assert res.status_code == 200
    assert res.json()["email_notifications"] is True


def test_patch_email_notifications_null_is_noop(client, db, auth_headers, test_user):
    test_user.email_notifications = False
    db.commit()

    res = client.patch(
        "/api/profile/me",
        headers=auth_headers,
        json={"email_notifications": None},
    )
    assert res.status_code == 200
    assert res.json()["email_notifications"] is False


# ---------------------------------------------------------------------------
# send_message triggers notification task
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_notify_delay(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.api.chat.notify_new_message.delay",
        lambda match_id, recipient_id, sender_id: calls.append(
            {"match_id": match_id, "recipient_id": recipient_id, "sender_id": sender_id}
        ),
    )
    return calls


def test_send_message_queues_notification(client, db, auth_headers, test_user, mock_notify_delay):
    from app.security import hash_password
    other = User(
        email="other_notify@howl.app",
        password_hash=hash_password("pass"),
        avatar_status=AvatarStatus.ready,
    )
    db.add(other)
    db.commit()
    db.refresh(other)

    match = Match(user1_id=min(test_user.id, other.id), user2_id=max(test_user.id, other.id))
    db.add(match)
    db.commit()
    db.refresh(match)

    client.post(
        f"/api/matches/{match.id}/messages",
        headers=auth_headers,
        json={"content": "Hello!"},
    )

    assert len(mock_notify_delay) == 1
    call = mock_notify_delay[0]
    assert call["match_id"] == match.id
    assert call["sender_id"] == test_user.id
    assert call["recipient_id"] == other.id
