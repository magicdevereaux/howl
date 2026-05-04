"""Tests for /api/auth endpoints: register, login, /me, refresh, and logout."""

import pytest

from app.models.refresh_token import RefreshToken


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
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "new@howl.app"
    assert "password_hash" not in data["user"]
    assert data["user"]["avatar_status"] == "pending"


def test_register_returns_usable_token(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "token@howl.app", "password": "securepassword"},
    )
    token = res.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "token@howl.app"


def test_register_duplicate_email(client, test_user):
    res = client.post(
        "/api/auth/register",
        json={"email": test_user.email, "password": "securepassword"},
    )
    assert res.status_code == 409
    assert "already registered" in res.json()["detail"]


def test_register_password_too_short(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "short@howl.app", "password": "abc123"},
    )
    assert res.status_code == 422


def test_register_invalid_email(client):
    res = client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": "securepassword"},
    )
    assert res.status_code == 422


def test_register_missing_fields(client):
    res = client.post("/api/auth/register", json={"email": "only@howl.app"})
    assert res.status_code == 422


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
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == test_user.email


def test_login_wrong_password(client, test_user):
    res = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "wrongpassword"},
    )
    assert res.status_code == 401
    assert "Invalid" in res.json()["detail"]


def test_login_unknown_email(client):
    res = client.post(
        "/api/auth/login",
        json={"email": "ghost@howl.app", "password": "securepassword"},
    )
    assert res.status_code == 401


def test_login_returns_usable_token(client, test_user):
    res = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "hunter2secure"},
    )
    token = res.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


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


def test_me_no_token(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_me_invalid_token(client):
    res = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer this.is.garbage"},
    )
    assert res.status_code == 401


def test_me_malformed_header(client):
    res = client.get("/api/auth/me", headers={"Authorization": "NotBearer token"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/auth/refresh
# ---------------------------------------------------------------------------

def test_refresh_returns_new_access_token(client, test_user):
    login = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "hunter2secure"},
    )
    refresh_token = login.json()["refresh_token"]

    res = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_refresh_token_gives_working_access_token(client, test_user):
    login = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "hunter2secure"},
    )
    refresh_token = login.json()["refresh_token"]

    new_access = client.post(
        "/api/auth/refresh", json={"refresh_token": refresh_token}
    ).json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200
    assert me.json()["email"] == test_user.email


def test_refresh_invalid_token_returns_401(client):
    res = client.post("/api/auth/refresh", json={"refresh_token": "notarealtoken"})
    assert res.status_code == 401


def test_refresh_persists_token_in_db(client, db, test_user):
    login = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "hunter2secure"},
    )
    raw = login.json()["refresh_token"]
    record = db.query(RefreshToken).filter(RefreshToken.token == raw).first()
    assert record is not None
    assert record.user_id == test_user.id
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

    res = client.post("/api/auth/refresh", json={"refresh_token": raw})
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

    res = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------

def test_logout_revokes_refresh_token(client, db, test_user):
    login = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "hunter2secure"},
    )
    raw = login.json()["refresh_token"]

    res = client.post("/api/auth/logout", json={"refresh_token": raw})
    assert res.status_code == 204

    record = db.query(RefreshToken).filter(RefreshToken.token == raw).first()
    db.refresh(record)
    assert record.revoked is True


def test_logout_then_refresh_returns_401(client, test_user):
    login = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "hunter2secure"},
    )
    raw = login.json()["refresh_token"]

    client.post("/api/auth/logout", json={"refresh_token": raw})

    res = client.post("/api/auth/refresh", json={"refresh_token": raw})
    assert res.status_code == 401


def test_logout_unknown_token_is_silent(client):
    """Logging out with an unrecognised token returns 204 — no error."""
    res = client.post("/api/auth/logout", json={"refresh_token": "unknowntoken"})
    assert res.status_code == 204


def test_logout_idempotent(client, test_user):
    """Logging out twice with the same token is safe."""
    login = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "hunter2secure"},
    )
    raw = login.json()["refresh_token"]

    client.post("/api/auth/logout", json={"refresh_token": raw})
    res = client.post("/api/auth/logout", json={"refresh_token": raw})
    assert res.status_code == 204


def test_refresh_token_cascade_deleted_with_account(client, db, test_user):
    """Deleting an account removes all its refresh tokens via CASCADE."""
    from app.security import create_access_token
    login = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "hunter2secure"},
    )
    raw = login.json()["refresh_token"]
    assert db.query(RefreshToken).filter(RefreshToken.token == raw).count() == 1

    headers = {"Authorization": f"Bearer {create_access_token(test_user.id)}"}
    client.delete("/api/profile/me", headers=headers)

    assert db.query(RefreshToken).filter(RefreshToken.token == raw).count() == 0
