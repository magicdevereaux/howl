"""Tests for email verification: token generation, expiry, and the verify-email endpoint."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.user import User

# ---------------------------------------------------------------------------
# Suppress console output from the email service during tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_verification_email(monkeypatch):
    monkeypatch.setattr("app.api.auth.send_verification_email", lambda *_: None)


# ---------------------------------------------------------------------------
# Registration generates a verification token
# ---------------------------------------------------------------------------

def test_register_creates_unverified_user(client, db):
    res = client.post("/api/auth/register", json={"email": "new@howl.app", "password": "securepass"})
    assert res.status_code == 201
    assert res.json()["user"]["is_email_verified"] is False


def test_register_sets_verification_token_on_user(client, db):
    client.post("/api/auth/register", json={"email": "tok@howl.app", "password": "securepass"})
    user = db.query(User).filter(User.email == "tok@howl.app").first()
    assert user is not None
    assert user.email_verification_token is not None
    assert len(user.email_verification_token) > 20


def test_register_sets_token_expiry_in_future(client, db):
    client.post("/api/auth/register", json={"email": "exp@howl.app", "password": "securepass"})
    user = db.query(User).filter(User.email == "exp@howl.app").first()
    expires_at = user.email_verification_token_expires_at
    assert expires_at is not None
    # Normalise for SQLite (naive) vs PostgreSQL (aware)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    assert expires_at > datetime.now(UTC)


def test_register_calls_email_service(client, db, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.api.auth.send_verification_email",
        lambda email, token: sent.append((email, token)),
    )
    client.post("/api/auth/register", json={"email": "mail@howl.app", "password": "securepass"})
    assert len(sent) == 1
    assert sent[0][0] == "mail@howl.app"
    assert len(sent[0][1]) > 20  # token is a real token


def test_unverified_user_can_still_login(client, db):
    client.post("/api/auth/register", json={"email": "login@howl.app", "password": "securepass"})
    res = client.post("/api/auth/login", json={"email": "login@howl.app", "password": "securepass"})
    assert res.status_code == 200
    assert "user" in res.json()


# ---------------------------------------------------------------------------
# POST /api/auth/verify-email
# ---------------------------------------------------------------------------

def _register_and_get_token(client, db, email="verify@howl.app"):
    client.post("/api/auth/register", json={"email": email, "password": "securepass"})
    user = db.query(User).filter(User.email == email).first()
    return user, user.email_verification_token


def test_verify_email_valid_token(client, db):
    user, token = _register_and_get_token(client, db)
    res = client.post("/api/auth/verify-email", json={"token": token})
    assert res.status_code == 200
    assert "verified" in res.json()["message"].lower()


def test_verify_email_marks_user_verified(client, db):
    user, token = _register_and_get_token(client, db, email="mark@howl.app")
    client.post("/api/auth/verify-email", json={"token": token})
    db.refresh(user)
    assert user.is_email_verified is True


def test_verify_email_clears_token_from_db(client, db):
    user, token = _register_and_get_token(client, db, email="clear@howl.app")
    client.post("/api/auth/verify-email", json={"token": token})
    db.refresh(user)
    assert user.email_verification_token is None
    assert user.email_verification_token_expires_at is None


def test_verify_email_invalid_token_returns_400(client):
    res = client.post("/api/auth/verify-email", json={"token": "notarealtoken"})
    assert res.status_code == 400


def test_verify_email_expired_token_returns_400(client, db):
    user, token = _register_and_get_token(client, db, email="expd@howl.app")
    # Backdate the expiry by 25 hours
    user.email_verification_token_expires_at = (
        datetime.now(UTC) - timedelta(hours=25)
    )
    db.commit()

    res = client.post("/api/auth/verify-email", json={"token": token})
    assert res.status_code == 400


def test_verify_email_token_cannot_be_reused(client, db):
    user, token = _register_and_get_token(client, db, email="reuse@howl.app")
    client.post("/api/auth/verify-email", json={"token": token})  # first use succeeds
    res = client.post("/api/auth/verify-email", json={"token": token})  # second use fails
    assert res.status_code == 400  # token was cleared after first use


def test_verify_email_is_email_verified_reflected_in_user_out(client, db):
    """After verification, the user's profile shows is_email_verified=True."""
    from app.security import create_access_token
    user, token = _register_and_get_token(client, db, email="reflect@howl.app")
    client.post("/api/auth/verify-email", json={"token": token})

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    res = client.get("/api/auth/me", headers=headers)
    assert res.status_code == 200
    assert res.json()["is_email_verified"] is True
