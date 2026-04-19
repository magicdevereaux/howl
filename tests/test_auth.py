"""Tests for /api/auth endpoints: register, login, and /me."""


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
