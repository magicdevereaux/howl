"""Tests for /api/auth endpoints: register, login, /me, refresh, and logout.

Tokens are now delivered as httpOnly cookies, not in the response body.
The TestClient stores and re-sends cookies automatically between calls on
the same client instance.  Cookies can also be injected via the Cookie
request header for unit-testing individual endpoints in isolation.
"""

import pytest

from app.models.refresh_token import RefreshToken
from app.security import create_access_token


# ---------------------------------------------------------------------------
# Helper — auth cookie header for one-off requests
# ---------------------------------------------------------------------------

def _cookie(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


# ---------------------------------------------------------------------------
# POST /api/auth/register
# ---------------------------------------------------------------------------

def test_register_success(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "new@howl.app", "password": "securepassword"},
    )
    assert res.status_code == 201
    data = res.json()
    # Tokens are in cookies, not the body
    assert "access_token" not in data
    assert "refresh_token" not in data
    assert data["user"]["email"] == "new@howl.app"
    assert "password_hash" not in data["user"]
    assert data["user"]["avatar_status"] == "pending"
    # Cookies must be set
    assert "access_token" in res.cookies
    assert "refresh_token" in res.cookies


def test_register_sets_httponly_cookies(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "cookie@howl.app", "password": "securepassword"},
    )
    assert res.status_code == 201
    # TestClient exposes Set-Cookie headers; verify both tokens are set
    set_cookies = res.headers.get_list("set-cookie") if hasattr(res.headers, "get_list") else [
        v for k, v in res.headers.items() if k.lower() == "set-cookie"
    ]
    assert any("access_token" in c for c in set_cookies)
    assert any("refresh_token" in c for c in set_cookies)


def test_register_cookie_allows_subsequent_requests(client):
    """Cookie set by register is automatically sent by the TestClient."""
    client.post(
        "/api/auth/register",
        json={"email": "subsequent@howl.app", "password": "securepassword"},
    )
    # Cookie is stored in client.cookies; /me should work without explicit header
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "subsequent@howl.app"


def test_register_duplicate_email(client, test_user):
    res = client.post(
        "/api/auth/register",
        json={"email": test_user.email, "password": "securepassword"},
    )
    assert res.status_code == 409
    assert "already registered" in res.json()["detail"]


def test_register_password_too_short(client):
    res = client.post("/api/auth/register", json={"email": "short@howl.app", "password": "abc123"})
    assert res.status_code == 422


def test_register_invalid_email(client):
    res = client.post("/api/auth/register", json={"email": "not-an-email", "password": "securepassword"})
    assert res.status_code == 422


def test_register_missing_fields(client):
    res = client.post("/api/auth/register", json={"email": "only@howl.app"})
    assert res.status_code == 422


def test_register_normalizes_email_to_lowercase(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "MixedCase@Howl.App", "password": "securepassword"},
    )
    assert res.status_code == 201
    assert res.json()["user"]["email"] == "mixedcase@howl.app"


def test_register_duplicate_email_case_insensitive(client, test_user):
    res = client.post(
        "/api/auth/register",
        json={"email": test_user.email.upper(), "password": "securepassword"},
    )
    assert res.status_code == 409
    assert "already registered" in res.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------

def test_login_success(client, test_user):
    res = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "hunter2secure"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" not in data
    assert data["user"]["email"] == test_user.email
    assert "access_token" in res.cookies


def test_login_cookie_allows_subsequent_requests(client, test_user):
    client.post("/api/auth/login", json={"email": test_user.email, "password": "hunter2secure"})
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == test_user.email


def test_login_wrong_password(client, test_user):
    res = client.post("/api/auth/login", json={"email": test_user.email, "password": "wrongpassword"})
    assert res.status_code == 401
    assert "Invalid" in res.json()["detail"]


def test_login_unknown_email(client):
    res = client.post("/api/auth/login", json={"email": "ghost@howl.app", "password": "securepassword"})
    assert res.status_code == 401


def test_login_case_insensitive_email(client, test_user):
    res = client.post(
        "/api/auth/login",
        json={"email": test_user.email.upper(), "password": "hunter2secure"},
    )
    assert res.status_code == 200
    assert res.json()["user"]["email"] == test_user.email


def test_login_mixed_case_email(client, test_user):
    mixed = "".join(c.upper() if i % 2 == 0 else c for i, c in enumerate(test_user.email))
    res = client.post(
        "/api/auth/login",
        json={"email": mixed, "password": "hunter2secure"},
    )
    assert res.status_code == 200
    assert res.json()["user"]["email"] == test_user.email


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------

def test_me_authenticated(client, auth_headers, test_user):
    res = client.get("/api/auth/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == test_user.email
    assert data["id"] == test_user.id
    assert "password_hash" not in data


def test_me_no_cookie_returns_401(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_me_invalid_cookie_returns_401(client):
    res = client.get("/api/auth/me", headers={"Cookie": "access_token=garbage.token.here"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/auth/refresh
# ---------------------------------------------------------------------------

def test_refresh_returns_user_and_sets_new_cookie(client, test_user):
    """Login sets both cookies; calling /refresh re-issues a new access_token cookie."""
    client.post("/api/auth/login", json={"email": test_user.email, "password": "hunter2secure"})
    res = client.post("/api/auth/refresh")
    assert res.status_code == 200
    assert "user" in res.json()
    assert "access_token" in res.cookies  # new access cookie set


def test_refresh_new_cookie_allows_auth(client, test_user):
    client.post("/api/auth/login", json={"email": test_user.email, "password": "hunter2secure"})
    client.post("/api/auth/refresh")  # rotates access cookie
    me = client.get("/api/auth/me")   # new cookie sent automatically
    assert me.status_code == 200
    assert me.json()["email"] == test_user.email


def test_refresh_no_cookie_returns_401(client):
    res = client.post("/api/auth/refresh")
    assert res.status_code == 401


def test_refresh_invalid_cookie_returns_401(client):
    res = client.post("/api/auth/refresh", headers={"Cookie": "refresh_token=notarealtoken"})
    assert res.status_code == 401


def test_refresh_persists_token_in_db(client, db, test_user):
    client.post("/api/auth/login", json={"email": test_user.email, "password": "hunter2secure"})
    record = db.query(RefreshToken).filter(RefreshToken.user_id == test_user.id).first()
    assert record is not None
    assert not record.revoked


def test_refresh_expired_token_returns_401(client, db, test_user):
    from datetime import datetime, timedelta, timezone
    raw = "expiredtoken" + "x" * 20
    db.add(RefreshToken(
        user_id=test_user.id,
        token=raw,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    ))
    db.commit()
    res = client.post("/api/auth/refresh", headers={"Cookie": f"refresh_token={raw}"})
    assert res.status_code == 401


def test_refresh_revoked_token_returns_401(client, db, test_user):
    from datetime import datetime, timedelta, timezone
    raw = "revokedtoken" + "x" * 20
    db.add(RefreshToken(
        user_id=test_user.id,
        token=raw,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        revoked=True,
    ))
    db.commit()
    res = client.post("/api/auth/refresh", headers={"Cookie": f"refresh_token={raw}"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------

def test_logout_clears_cookies(client, test_user):
    client.post("/api/auth/login", json={"email": test_user.email, "password": "hunter2secure"})
    res = client.post("/api/auth/logout")
    assert res.status_code == 204
    # Cookies should be cleared (expired/deleted) in the response
    set_cookies = [v for k, v in res.headers.items() if k.lower() == "set-cookie"]
    assert any("access_token" in c and ("expires" in c.lower() or "max-age=0" in c.lower()) for c in set_cookies)


def test_logout_revokes_refresh_token_in_db(client, db, test_user):
    client.post("/api/auth/login", json={"email": test_user.email, "password": "hunter2secure"})
    record = db.query(RefreshToken).filter(RefreshToken.user_id == test_user.id).first()
    raw = record.token

    client.post("/api/auth/logout")

    db.refresh(record)
    assert record.revoked is True


def test_logout_then_refresh_returns_401(client, db, test_user):
    client.post("/api/auth/login", json={"email": test_user.email, "password": "hunter2secure"})
    record = db.query(RefreshToken).filter(RefreshToken.user_id == test_user.id).first()
    raw = record.token

    client.post("/api/auth/logout")

    # Manually inject the revoked token as a cookie to simulate a stale browser
    res = client.post("/api/auth/refresh", headers={"Cookie": f"refresh_token={raw}"})
    assert res.status_code == 401


def test_logout_without_cookie_is_silent(client):
    """Logging out without a session returns 204 — no error."""
    res = client.post("/api/auth/logout")
    assert res.status_code == 204


def test_refresh_token_cascade_deleted_with_account(client, db, test_user):
    """Deleting an account removes all its refresh tokens via CASCADE."""
    client.post("/api/auth/login", json={"email": test_user.email, "password": "hunter2secure"})
    record = db.query(RefreshToken).filter(RefreshToken.user_id == test_user.id).first()
    raw = record.token
    assert db.query(RefreshToken).filter(RefreshToken.token == raw).count() == 1

    client.delete("/api/profile/me", headers={"Cookie": f"access_token={create_access_token(test_user.id)}"})

    assert db.query(RefreshToken).filter(RefreshToken.token == raw).count() == 0
