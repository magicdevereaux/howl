"""Tests for /api/push-tokens — Expo push token registration."""

from app.models.push_token import PushToken
from app.models.user import AvatarStatus, User
from app.security import hash_password


def _make_user(db, *, email: str) -> User:
    user = User(email=email, password_hash=hash_password("testpass1"), avatar_status=AvatarStatus.ready)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_register_push_token(client, db, auth_headers, test_user):
    res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[abc123]"})
    assert res.status_code == 204

    record = db.query(PushToken).filter(PushToken.token == "ExponentPushToken[abc123]").first()
    assert record is not None
    assert record.user_id == test_user.id


def test_register_push_token_idempotent(client, db, auth_headers, test_user):
    for _ in range(2):
        res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[dup]"})
        assert res.status_code == 204

    assert db.query(PushToken).filter(PushToken.token == "ExponentPushToken[dup]").count() == 1


def test_register_push_token_reassigns_existing_owner(client, db, auth_headers, test_user):
    """A shared device's token should move to whoever is now logged in."""
    other = _make_user(db, email="otherdevice@howl.app")
    db.add(PushToken(user_id=other.id, token="ExponentPushToken[shared]"))
    db.commit()

    res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[shared]"})
    assert res.status_code == 204

    record = db.query(PushToken).filter(PushToken.token == "ExponentPushToken[shared]").first()
    assert record.user_id == test_user.id
    assert db.query(PushToken).filter(PushToken.token == "ExponentPushToken[shared]").count() == 1


def test_register_push_token_requires_auth(client):
    res = client.post("/api/push-tokens", json={"token": "ExponentPushToken[noauth]"})
    assert res.status_code == 401


def test_register_push_token_rejects_blank(client, auth_headers):
    res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "   "})
    assert res.status_code == 422


def test_unregister_push_token(client, db, auth_headers, test_user):
    db.add(PushToken(user_id=test_user.id, token="ExponentPushToken[remove]"))
    db.commit()

    res = client.request(
        "DELETE", "/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[remove]"}
    )
    assert res.status_code == 204
    assert db.query(PushToken).filter(PushToken.token == "ExponentPushToken[remove]").count() == 0


def test_unregister_unknown_token_is_silent(client, auth_headers):
    res = client.request(
        "DELETE", "/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[ghost]"}
    )
    assert res.status_code == 204


def test_unregister_does_not_remove_other_users_token(client, db, auth_headers, test_user):
    other = _make_user(db, email="keepme@howl.app")
    db.add(PushToken(user_id=other.id, token="ExponentPushToken[keep]"))
    db.commit()

    res = client.request(
        "DELETE", "/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[keep]"}
    )
    assert res.status_code == 204
    assert db.query(PushToken).filter(PushToken.token == "ExponentPushToken[keep]").count() == 1
