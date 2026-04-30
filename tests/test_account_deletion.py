"""Tests for DELETE /api/profile/me (account deletion)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.match import Match
from app.models.message import Message
from app.models.swipe import Swipe, SwipeDirection
from app.models.user import AvatarStatus, User
from app.security import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _make_match(db, a: User, b: User) -> Match:
    m = Match(user1_id=min(a.id, b.id), user2_id=max(a.id, b.id))
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _make_message(db, *, match_id: int, sender_id: int, content: str = "hi") -> Message:
    msg = Message(match_id=match_id, sender_id=sender_id, content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def _make_swipe(db, *, user_id: int, target_user_id: int, direction: SwipeDirection) -> Swipe:
    s = Swipe(user_id=user_id, target_user_id=target_user_id, direction=direction)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# Auth guards
# ---------------------------------------------------------------------------

def test_delete_unauthenticated(client):
    res = client.delete("/api/profile/me")
    assert res.status_code == 401


def test_delete_invalid_token(client):
    res = client.delete("/api/profile/me", headers={"Authorization": "Bearer garbage"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Successful deletion
# ---------------------------------------------------------------------------

def test_delete_returns_204(client, auth_headers):
    res = client.delete("/api/profile/me", headers=auth_headers)
    assert res.status_code == 204
    assert res.content == b""


def test_delete_removes_user_from_db(client, db, auth_headers, test_user):
    user_id = test_user.id
    client.delete("/api/profile/me", headers=auth_headers)
    assert db.query(User).filter(User.id == user_id).first() is None


def test_old_token_returns_401_after_deletion(client, auth_headers):
    client.delete("/api/profile/me", headers=auth_headers)
    res = client.get("/api/profile/me", headers=auth_headers)
    assert res.status_code == 401


def test_can_reregister_with_same_email_after_deletion(client, auth_headers, test_user):
    email = test_user.email
    client.delete("/api/profile/me", headers=auth_headers)
    res = client.post("/api/auth/register", json={"email": email, "password": "newpass123"})
    assert res.status_code == 201


# ---------------------------------------------------------------------------
# Cascade verification
# ---------------------------------------------------------------------------

def test_delete_cascades_swipes_made_by_user(client, db, auth_headers, test_user):
    other = _make_user(db, email="other@howl.app")
    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.like)

    client.delete("/api/profile/me", headers=auth_headers)

    assert db.query(Swipe).filter(Swipe.user_id == test_user.id).count() == 0


def test_delete_cascades_swipes_on_user(client, db, auth_headers, test_user):
    other = _make_user(db, email="other2@howl.app")
    _make_swipe(db, user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like)

    client.delete("/api/profile/me", headers=auth_headers)

    assert db.query(Swipe).filter(Swipe.target_user_id == test_user.id).count() == 0


def test_delete_cascades_matches(client, db, auth_headers, test_user):
    other = _make_user(db, email="other3@howl.app")
    match = _make_match(db, test_user, other)
    match_id = match.id  # capture before cascade-delete detaches the object

    client.delete("/api/profile/me", headers=auth_headers)

    assert db.query(Match).filter(Match.id == match_id).first() is None


def test_delete_cascades_messages_in_match(client, db, auth_headers, test_user):
    other = _make_user(db, email="other4@howl.app")
    match = _make_match(db, test_user, other)
    match_id = match.id
    _make_message(db, match_id=match_id, sender_id=test_user.id, content="hello")
    _make_message(db, match_id=match_id, sender_id=other.id, content="hey back")

    client.delete("/api/profile/me", headers=auth_headers)

    assert db.query(Message).filter(Message.match_id == match_id).count() == 0


def test_delete_cascades_all_data(client, db, auth_headers, test_user):
    """Full scenario: swipes, matches, and messages all gone after deletion."""
    other = _make_user(db, email="other5@howl.app")
    third = _make_user(db, email="third@howl.app")

    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.like)
    _make_swipe(db, user_id=third.id, target_user_id=test_user.id, direction=SwipeDirection.pass_)

    match = _make_match(db, test_user, other)
    match_id = match.id
    _make_message(db, match_id=match_id, sender_id=test_user.id)
    _make_message(db, match_id=match_id, sender_id=other.id)

    user_id = test_user.id
    client.delete("/api/profile/me", headers=auth_headers)

    assert db.query(User).filter(User.id == user_id).first() is None
    assert db.query(Swipe).filter(
        (Swipe.user_id == user_id) | (Swipe.target_user_id == user_id)
    ).count() == 0
    assert db.query(Match).filter(Match.id == match_id).first() is None
    assert db.query(Message).filter(Message.match_id == match_id).count() == 0


# ---------------------------------------------------------------------------
# Other users unaffected
# ---------------------------------------------------------------------------

def test_delete_does_not_affect_other_users(client, db, auth_headers, test_user):
    other = _make_user(db, email="safe@howl.app")
    third = _make_user(db, email="also_safe@howl.app")
    other_match = _make_match(db, other, third)
    _make_message(db, match_id=other_match.id, sender_id=other.id)
    _make_swipe(db, user_id=other.id, target_user_id=third.id, direction=SwipeDirection.pass_)

    client.delete("/api/profile/me", headers=auth_headers)

    # other and third are still there
    assert db.query(User).filter(User.id == other.id).first() is not None
    assert db.query(User).filter(User.id == third.id).first() is not None
    assert db.query(Match).filter(Match.id == other_match.id).first() is not None
    assert db.query(Message).filter(Message.match_id == other_match.id).count() == 1


# ---------------------------------------------------------------------------
# Avatar file deletion
# ---------------------------------------------------------------------------

def test_delete_removes_avatar_file(client, db, auth_headers, test_user, tmp_path, monkeypatch):
    """Avatar file is unlinked when avatar_url is set."""
    fake_file = tmp_path / "abc123.png"
    fake_file.write_bytes(b"PNG")
    test_user.avatar_url = "/avatars/abc123.png"
    db.commit()

    monkeypatch.setattr("app.api.profile.AVATAR_DIR", tmp_path)

    client.delete("/api/profile/me", headers=auth_headers)

    assert not fake_file.exists()


def test_delete_succeeds_when_no_avatar_url(client, db, auth_headers, test_user):
    """Deletion proceeds normally even if avatar_url is null."""
    test_user.avatar_url = None
    db.commit()

    res = client.delete("/api/profile/me", headers=auth_headers)
    assert res.status_code == 204


def test_delete_succeeds_when_avatar_file_missing_from_disk(client, db, auth_headers, test_user, tmp_path, monkeypatch):
    """A missing file on disk (e.g. after Railway redeploy) never blocks account deletion."""
    test_user.avatar_url = "/avatars/gone.png"
    db.commit()

    monkeypatch.setattr("app.api.profile.AVATAR_DIR", tmp_path)
    # File doesn't exist on disk — should not raise

    res = client.delete("/api/profile/me", headers=auth_headers)
    assert res.status_code == 204
