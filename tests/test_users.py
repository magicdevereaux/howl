"""Tests for GET /api/users/browse."""

import pytest

from app.models.user import AvatarStatus, User
from app.security import hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, *, email: str, avatar_status: AvatarStatus = AvatarStatus.ready, **kwargs) -> User:
    """Insert a minimal user into the test DB and return it."""
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        avatar_status=avatar_status,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Auth guards
# ---------------------------------------------------------------------------

def test_browse_unauthenticated(client):
    res = client.get("/api/users/browse")
    assert res.status_code == 401


def test_browse_invalid_token(client):
    res = client.get(
        "/api/users/browse",
        headers={"Authorization": "Bearer garbage.token.here"},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def test_browse_returns_only_ready_users(client, db, auth_headers):
    """Pending and failed users are excluded from browse results."""
    _make_user(db, email="pending@howl.app", avatar_status=AvatarStatus.pending, animal="fox")
    _make_user(db, email="failed@howl.app", avatar_status=AvatarStatus.failed, animal="wolf")
    ready = _make_user(db, email="ready@howl.app", avatar_status=AvatarStatus.ready, animal="owl")

    res = client.get("/api/users/browse", headers=auth_headers)
    assert res.status_code == 200
    emails_returned = [u["animal"] for u in res.json()]
    assert ready.animal in emails_returned
    assert len([u for u in res.json() if u["animal"] == "fox"]) == 0
    assert len([u for u in res.json() if u["animal"] == "wolf"]) == 0


def test_browse_excludes_current_user(client, db, auth_headers, test_user):
    """The logged-in user should not appear in their own browse feed."""
    # Make test_user ready so it would otherwise appear
    test_user.avatar_status = AvatarStatus.ready
    test_user.animal = "bear"
    db.commit()

    res = client.get("/api/users/browse", headers=auth_headers)
    assert res.status_code == 200
    # test_user's animal is bear — it must not appear in results
    # (test_user is the only user in the DB, so results should be empty)
    assert res.json() == []


def test_browse_empty_when_no_other_users(client, auth_headers):
    """Returns an empty list (not 404) when no other users exist."""
    res = client.get("/api/users/browse", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

def test_browse_returns_correct_fields(client, db, auth_headers):
    """Browse response includes public fields and excludes sensitive ones."""
    _make_user(
        db,
        email="fox@howl.app",
        avatar_status=AvatarStatus.ready,
        name="Remy",
        location="Paris, FR",
        bio="A curious fox who loves exploring dense forests at dusk.",
        animal="fox",
        personality_traits=["curious", "clever"],
        avatar_description="A rust-furred fox-human hybrid.",
    )

    res = client.get("/api/users/browse", headers=auth_headers)
    assert res.status_code == 200
    users = res.json()
    assert len(users) == 1
    u = users[0]

    # Public fields present
    assert u["name"] == "Remy"
    assert u["location"] == "Paris, FR"
    assert u["bio"] == "A curious fox who loves exploring dense forests at dusk."
    assert u["animal"] == "fox"
    assert u["personality_traits"] == ["curious", "clever"]
    assert u["avatar_description"] == "A rust-furred fox-human hybrid."

    # Sensitive fields absent
    assert "email" not in u
    assert "password_hash" not in u
    assert "id" not in u


def test_browse_handles_null_optional_fields(client, db, auth_headers):
    """Users with no name/location/bio/traits still appear without errors."""
    _make_user(db, email="bare@howl.app", avatar_status=AvatarStatus.ready, animal="deer")

    res = client.get("/api/users/browse", headers=auth_headers)
    assert res.status_code == 200
    u = res.json()[0]
    assert u["animal"] == "deer"
    assert u["name"] is None
    assert u["location"] is None
    assert u["bio"] is None
    assert u["personality_traits"] is None


def test_browse_returns_multiple_users(client, db, auth_headers):
    """All ready users (excluding current) are returned."""
    for i in range(3):
        _make_user(
            db,
            email=f"multi{i}@howl.app",
            avatar_status=AvatarStatus.ready,
            animal="wolf",
        )

    res = client.get("/api/users/browse", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 3
