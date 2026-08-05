"""Tests for /api/mobile/auth/* — the auth surface the shipped Expo app uses.

These endpoints return tokens in the JSON body instead of setting httpOnly
cookies. They previously had no test coverage at all.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.security import hash_password


@pytest.fixture
def mobile_user(db):
    user = User(email="otter@howl.app", password_hash=hash_password("riverstone9"))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """Default to an open limiter; the rate-limit tests opt back in."""
    monkeypatch.setattr("app.api.auth.check_rate_limit", lambda *a, **kw: (False, 0))


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------

def test_mobile_register_returns_tokens_in_body(client, monkeypatch):
    monkeypatch.setattr("app.api.mobile_auth.send_verification_email", lambda *a: None)
    res = client.post(
        "/api/mobile/auth/register",
        json={"email": "newbie@howl.app", "password": "hunter2secure"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["email"] == "newbie@howl.app"
    # tokens must not also be set as cookies on the mobile path
    assert "access_token" not in res.cookies


def test_mobile_register_duplicate_email_conflicts(client, mobile_user, monkeypatch):
    monkeypatch.setattr("app.api.mobile_auth.send_verification_email", lambda *a: None)
    res = client.post(
        "/api/mobile/auth/register",
        json={"email": mobile_user.email, "password": "riverstone9"},
    )
    assert res.status_code == 409


def test_mobile_register_verification_token_lasts_24h(client, db, monkeypatch):
    """Regression: this used to reuse the 1-hour password-reset constant."""
    monkeypatch.setattr("app.api.mobile_auth.send_verification_email", lambda *a: None)
    res = client.post(
        "/api/mobile/auth/register",
        json={"email": "badger@howl.app", "password": "hunter2secure"},
    )
    assert res.status_code == 201

    user = db.query(User).filter(User.email == "badger@howl.app").first()
    expires_at = user.email_verification_token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    remaining = expires_at - datetime.now(UTC)
    assert remaining > timedelta(hours=23)


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

def test_mobile_login_success(client, mobile_user):
    res = client.post(
        "/api/mobile/auth/login",
        json={"email": mobile_user.email, "password": "riverstone9"},
    )
    assert res.status_code == 200
    assert res.json()["access_token"]
    assert res.json()["refresh_token"]


def test_mobile_login_wrong_password(client, mobile_user):
    res = client.post(
        "/api/mobile/auth/login",
        json={"email": mobile_user.email, "password": "wrongpassword"},
    )
    assert res.status_code == 401


def test_mobile_login_is_rate_limited(client, mobile_user, monkeypatch):
    """Regression: this endpoint had no limiter, bypassing the web protection."""
    monkeypatch.setattr("app.api.auth.check_rate_limit", lambda *a, **kw: (True, 42))
    res = client.post(
        "/api/mobile/auth/login",
        json={"email": mobile_user.email, "password": "riverstone9"},
    )
    assert res.status_code == 429
    assert res.headers["Retry-After"] == "42"


def test_mobile_login_rate_limit_precedes_credential_check(client, monkeypatch):
    """A limited request must 429 rather than leak whether the account exists."""
    monkeypatch.setattr("app.api.auth.check_rate_limit", lambda *a, **kw: (True, 30))
    res = client.post(
        "/api/mobile/auth/login",
        json={"email": "nobody@howl.app", "password": "whatever123"},
    )
    assert res.status_code == 429


# ---------------------------------------------------------------------------
# refresh / logout
# ---------------------------------------------------------------------------

def test_mobile_refresh_issues_new_access_token(client, mobile_user):
    login = client.post(
        "/api/mobile/auth/login",
        json={"email": mobile_user.email, "password": "riverstone9"},
    ).json()

    res = client.post(
        "/api/mobile/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )
    assert res.status_code == 200
    assert res.json()["access_token"]
    assert res.json()["user"]["id"] == mobile_user.id


def test_mobile_refresh_rejects_unknown_token(client):
    res = client.post("/api/mobile/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert res.status_code == 401


def test_mobile_refresh_rejects_expired_token(client, db, mobile_user):
    db.add(
        RefreshToken(
            user_id=mobile_user.id,
            token="expired-token",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    db.commit()
    res = client.post("/api/mobile/auth/refresh", json={"refresh_token": "expired-token"})
    assert res.status_code == 401


def test_mobile_logout_revokes_refresh_token(client, mobile_user):
    login = client.post(
        "/api/mobile/auth/login",
        json={"email": mobile_user.email, "password": "riverstone9"},
    ).json()
    token = login["refresh_token"]

    assert client.post("/api/mobile/auth/logout", json={"refresh_token": token}).status_code == 204
    # the revoked token can no longer be exchanged
    assert client.post("/api/mobile/auth/refresh", json={"refresh_token": token}).status_code == 401


# ---------------------------------------------------------------------------
# bearer tokens work against the shared API surface
# ---------------------------------------------------------------------------

def test_mobile_access_token_authenticates_shared_endpoints(client, mobile_user):
    login = client.post(
        "/api/mobile/auth/login",
        json={"email": mobile_user.email, "password": "riverstone9"},
    ).json()

    res = client.get(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert res.status_code == 200
    assert res.json()["id"] == mobile_user.id
