"""Tests for /api/profile endpoints: get and update profile."""

import pytest

from app.models.user import AvatarStatus


# Prevent every test in this module from hitting the real Celery/Redis stack.
@pytest.fixture(autouse=True)
def mock_celery(monkeypatch):
    monkeypatch.setattr("app.api.profile.generate_avatar.delay", lambda user_id: None)


# ---------------------------------------------------------------------------
# GET /api/profile/me
# ---------------------------------------------------------------------------

def test_get_my_profile(client, auth_headers, test_user):
    res = client.get("/api/profile/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == test_user.id
    assert data["email"] == test_user.email
    assert data["bio"] is None
    assert "password_hash" not in data


def test_get_my_profile_unauthenticated(client):
    res = client.get("/api/profile/me")
    assert res.status_code == 401


def test_get_my_profile_invalid_token(client):
    res = client.get(
        "/api/profile/me",
        headers={"Authorization": "Bearer garbage"},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# PATCH /api/profile/me
# ---------------------------------------------------------------------------

def test_update_bio_success(client, auth_headers):
    bio = "A lone wolf who loves midnight runs and howling at the moon."
    res = client.patch("/api/profile/me", headers=auth_headers, json={"bio": bio})
    assert res.status_code == 200
    data = res.json()
    assert data["bio"] == bio
    # Bio update resets avatar for regeneration
    assert data["avatar_status"] == "pending"
    assert data["animal"] is None


def test_update_bio_triggers_task(client, auth_headers, monkeypatch):
    """Verify that generate_avatar.delay is called with the user's id."""
    called_with = []
    monkeypatch.setattr(
        "app.api.profile.generate_avatar.delay",
        lambda user_id: called_with.append(user_id),
    )
    res = client.patch(
        "/api/profile/me",
        headers=auth_headers,
        json={"bio": "This bio is definitely long enough to trigger generation."},
    )
    assert res.status_code == 200
    assert len(called_with) == 1
    assert called_with[0] == res.json()["id"]


def test_update_bio_too_short(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"bio": "Short"})
    assert res.status_code == 422


def test_update_bio_too_long(client, auth_headers):
    res = client.patch(
        "/api/profile/me", headers=auth_headers, json={"bio": "x" * 501}
    )
    assert res.status_code == 422


def test_update_bio_exactly_min_length(client, auth_headers):
    # 10 chars is the minimum
    res = client.patch(
        "/api/profile/me", headers=auth_headers, json={"bio": "1234567890"}
    )
    assert res.status_code == 200


def test_update_bio_exactly_max_length(client, auth_headers):
    # 500 chars is the maximum
    res = client.patch(
        "/api/profile/me", headers=auth_headers, json={"bio": "x" * 500}
    )
    assert res.status_code == 200


def test_update_bio_none_is_noop(client, auth_headers, test_user):
    """Passing bio=null should not reset avatar_status."""
    original_status = test_user.avatar_status.value
    res = client.patch(
        "/api/profile/me", headers=auth_headers, json={"bio": None}
    )
    assert res.status_code == 200
    assert res.json()["avatar_status"] == original_status


def test_update_bio_unauthenticated(client):
    res = client.patch(
        "/api/profile/me",
        json={"bio": "This should be rejected without a token."},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/profile/{user_id}
# ---------------------------------------------------------------------------

def test_get_profile_by_id(client, test_user):
    res = client.get(f"/api/profile/{test_user.id}")
    assert res.status_code == 200
    assert res.json()["id"] == test_user.id
    assert res.json()["email"] == test_user.email


def test_get_profile_not_found(client):
    res = client.get("/api/profile/99999")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()
