"""Tests for POST /api/auth/forgot-password and POST /api/auth/reset-password."""

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.security import hash_password, verify_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token(db, user_id: int, *, used: bool = False, expired: bool = False) -> PasswordResetToken:
    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(hours=2) if expired else now + timedelta(hours=1)
    tok = PasswordResetToken(
        user_id=user_id,
        token=secrets.token_urlsafe(32),
        expires_at=expires_at,
        used=used,
    )
    db.add(tok)
    db.commit()
    db.refresh(tok)
    return tok


# ---------------------------------------------------------------------------
# Suppress console output from the email service during tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_email(monkeypatch):
    monkeypatch.setattr("app.api.auth.send_password_reset_email", lambda *_: None)


# ---------------------------------------------------------------------------
# POST /api/auth/forgot-password
# ---------------------------------------------------------------------------

def test_forgot_password_valid_email_returns_200(client, test_user):
    res = client.post("/api/auth/forgot-password", json={"email": test_user.email})
    assert res.status_code == 200
    assert "reset" in res.json()["message"].lower()


def test_forgot_password_unknown_email_also_returns_200(client):
    """Response is identical whether the email exists or not — prevents enumeration."""
    res = client.post("/api/auth/forgot-password", json={"email": "nobody@howl.app"})
    assert res.status_code == 200
    assert "reset" in res.json()["message"].lower()


def test_forgot_password_same_message_for_both(client, test_user):
    res_known = client.post("/api/auth/forgot-password", json={"email": test_user.email})
    res_unknown = client.post("/api/auth/forgot-password", json={"email": "ghost@howl.app"})
    assert res_known.json()["message"] == res_unknown.json()["message"]


def test_forgot_password_creates_token_in_db(client, db, test_user):
    client.post("/api/auth/forgot-password", json={"email": test_user.email})
    tok = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == test_user.id).first()
    assert tok is not None
    assert not tok.used


def test_forgot_password_invalidates_previous_unused_tokens(client, db, test_user):
    old = _make_token(db, test_user.id)
    client.post("/api/auth/forgot-password", json={"email": test_user.email})
    db.refresh(old)
    assert old.used is True


def test_forgot_password_calls_email_service(client, test_user, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.api.auth.send_password_reset_email",
        lambda email, token: sent.append((email, token)),
    )
    client.post("/api/auth/forgot-password", json={"email": test_user.email})
    assert len(sent) == 1
    assert sent[0][0] == test_user.email


def test_forgot_password_no_email_service_call_for_unknown(client, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.api.auth.send_password_reset_email",
        lambda *_: sent.append(True),
    )
    client.post("/api/auth/forgot-password", json={"email": "nobody@howl.app"})
    assert len(sent) == 0


# ---------------------------------------------------------------------------
# POST /api/auth/reset-password
# ---------------------------------------------------------------------------

def test_reset_password_valid_token_returns_200(client, db, test_user):
    tok = _make_token(db, test_user.id)
    res = client.post("/api/auth/reset-password", json={"token": tok.token, "new_password": "newpass99"})
    assert res.status_code == 200
    assert "successful" in res.json()["message"].lower()


def test_reset_password_updates_hash_in_db(client, db, test_user):
    tok = _make_token(db, test_user.id)
    client.post("/api/auth/reset-password", json={"token": tok.token, "new_password": "freshnewpass"})
    db.refresh(test_user)
    assert verify_password("freshnewpass", test_user.password_hash)


def test_reset_password_marks_token_used(client, db, test_user):
    tok = _make_token(db, test_user.id)
    client.post("/api/auth/reset-password", json={"token": tok.token, "new_password": "newpass99"})
    db.refresh(tok)
    assert tok.used is True


def test_reset_password_expired_token_returns_400(client, db, test_user):
    tok = _make_token(db, test_user.id, expired=True)
    res = client.post("/api/auth/reset-password", json={"token": tok.token, "new_password": "newpass99"})
    assert res.status_code == 400


def test_reset_password_used_token_returns_400(client, db, test_user):
    tok = _make_token(db, test_user.id, used=True)
    res = client.post("/api/auth/reset-password", json={"token": tok.token, "new_password": "newpass99"})
    assert res.status_code == 400


def test_reset_password_invalid_token_returns_400(client):
    res = client.post("/api/auth/reset-password", json={"token": "notarealtoken", "new_password": "newpass99"})
    assert res.status_code == 400


def test_reset_password_too_short_returns_422(client, db, test_user):
    tok = _make_token(db, test_user.id)
    res = client.post("/api/auth/reset-password", json={"token": tok.token, "new_password": "short"})
    assert res.status_code == 422


def test_reset_password_token_cannot_be_reused(client, db, test_user):
    tok = _make_token(db, test_user.id)
    client.post("/api/auth/reset-password", json={"token": tok.token, "new_password": "firstpass1"})
    res = client.post("/api/auth/reset-password", json={"token": tok.token, "new_password": "secondpass1"})
    assert res.status_code == 400


def test_can_login_with_new_password(client, db, test_user):
    tok = _make_token(db, test_user.id)
    client.post("/api/auth/reset-password", json={"token": tok.token, "new_password": "brandnewpass"})
    res = client.post("/api/auth/login", json={"email": test_user.email, "password": "brandnewpass"})
    assert res.status_code == 200
    assert "access_token" in res.json()


def test_old_password_no_longer_works_after_reset(client, db, test_user):
    original_hash = test_user.password_hash  # hunter2secure
    tok = _make_token(db, test_user.id)
    client.post("/api/auth/reset-password", json={"token": tok.token, "new_password": "brandnewpass"})
    res = client.post("/api/auth/login", json={"email": test_user.email, "password": "hunter2secure"})
    assert res.status_code == 401
