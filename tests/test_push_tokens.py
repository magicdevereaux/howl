"""Tests for /api/push-tokens — Expo push token registration."""

from datetime import UTC, datetime, timedelta

from app.models.push_token import PushToken
from app.models.user import AvatarStatus, User
from app.security import hash_password


def _make_user(db, *, email: str) -> User:
    user = User(email=email, password_hash=hash_password("testpass1"), avatar_status=AvatarStatus.ready, animal="wolf")
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


# ---------------------------------------------------------------------------
# Format validation (GAPS #57)
#
# Without this, garbage strings accumulate forever -- only DeviceNotRegistered
# tickets ever get pruned, and every non-Expo string is still sent to Expo's
# API on every notification for that user.
# ---------------------------------------------------------------------------

def test_register_push_token_rejects_wrong_shape(client, auth_headers):
    res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "not-a-real-token"})
    assert res.status_code == 422


def test_register_push_token_rejects_missing_brackets(client, auth_headers):
    res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushTokenabc123"})
    assert res.status_code == 422


def test_register_push_token_accepts_expo_alias(client, db, auth_headers, test_user):
    """The older `ExpoPushToken[...]` alias, not just `ExponentPushToken[...]`."""
    res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "ExpoPushToken[abc123]"})
    assert res.status_code == 204
    assert db.query(PushToken).filter(PushToken.token == "ExpoPushToken[abc123]").count() == 1


def test_register_push_token_rejects_empty_brackets(client, auth_headers):
    res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[]"})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Per-user cap (GAPS #57)
#
# Without this, one account can register unbounded distinct tokens and every
# push to that user then queries and messages all of them.
# ---------------------------------------------------------------------------

def test_register_push_token_evicts_oldest_beyond_cap(client, db, auth_headers, test_user):
    # 10 pre-existing tokens, oldest to newest, all already at the cap.
    base = datetime.now(UTC) - timedelta(days=1)
    for i in range(10):
        db.add(PushToken(
            user_id=test_user.id,
            token=f"ExponentPushToken[old{i}]",
            created_at=base + timedelta(minutes=i),
        ))
    db.commit()
    assert db.query(PushToken).filter(PushToken.user_id == test_user.id).count() == 10

    res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[new]"})
    assert res.status_code == 204

    rows = db.query(PushToken).filter(PushToken.user_id == test_user.id).all()
    assert len(rows) == 10, "cap must still hold after registering an 11th token"
    tokens = {r.token for r in rows}
    assert "ExponentPushToken[new]" in tokens
    assert "ExponentPushToken[old0]" not in tokens, "the oldest token should have been evicted"
    assert "ExponentPushToken[old9]" in tokens, "the next-oldest tokens must survive"


def test_register_push_token_cap_does_not_affect_other_users(client, db, auth_headers, test_user):
    other = _make_user(db, email="capneighbor@howl.app")
    for i in range(10):
        db.add(PushToken(user_id=other.id, token=f"ExponentPushToken[other{i}]"))
    db.commit()

    res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[mine]"})
    assert res.status_code == 204

    assert db.query(PushToken).filter(PushToken.user_id == other.id).count() == 10
    assert db.query(PushToken).filter(PushToken.user_id == test_user.id).count() == 1


def test_reassigned_token_is_not_immediately_evicted_as_stale(client, db, auth_headers, test_user):
    """A token reassigned from another account must not look 'oldest' and get
    evicted the instant it arrives, just because its created_at predates the
    new owner's other tokens."""
    other = _make_user(db, email="staledevice@howl.app")
    ancient = datetime.now(UTC) - timedelta(days=365)
    db.add(PushToken(user_id=other.id, token="ExponentPushToken[ancient]", created_at=ancient))
    for i in range(9):
        db.add(PushToken(user_id=test_user.id, token=f"ExponentPushToken[mine{i}]"))
    db.commit()
    assert db.query(PushToken).filter(PushToken.user_id == test_user.id).count() == 9

    res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[ancient]"})
    assert res.status_code == 204

    record = db.query(PushToken).filter(PushToken.token == "ExponentPushToken[ancient]").first()
    assert record.user_id == test_user.id, "reassignment must still happen"


# ---------------------------------------------------------------------------
# Reassignment is logged (GAPS #57)
# ---------------------------------------------------------------------------

def test_reassignment_is_logged_for_audit(client, db, auth_headers, test_user, caplog):
    other = _make_user(db, email="auditme@howl.app")
    db.add(PushToken(user_id=other.id, token="ExponentPushToken[audit]"))
    db.commit()

    with caplog.at_level("WARNING", logger="app.api.push_tokens"):
        res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[audit]"})
    assert res.status_code == 204

    assert any(
        "reassigning" in rec.getMessage()
        and str(other.id) in rec.getMessage()
        and str(test_user.id) in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


def test_fresh_registration_is_not_logged_as_a_reassignment(client, auth_headers, caplog):
    with caplog.at_level("WARNING", logger="app.api.push_tokens"):
        res = client.post("/api/push-tokens", headers=auth_headers, json={"token": "ExponentPushToken[fresh]"})
    assert res.status_code == 204
    assert not any("reassigning" in rec.getMessage() for rec in caplog.records)


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
