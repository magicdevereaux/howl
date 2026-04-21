"""Tests for GET /api/avatar/status and POST /api/avatar/regenerate."""

from datetime import datetime, timezone

import pytest

from app.models.user import AvatarStatus


# Prevent all tests in this module from hitting the real Celery/Redis stack.
@pytest.fixture(autouse=True)
def mock_celery(monkeypatch):
    monkeypatch.setattr("app.api.avatar.generate_avatar.delay", lambda user_id: None)


# ---------------------------------------------------------------------------
# GET /api/avatar/status — unauthenticated / bad-auth cases
# ---------------------------------------------------------------------------

def test_status_unauthenticated(client):
    res = client.get("/api/avatar/status")
    assert res.status_code == 401


def test_status_invalid_token(client):
    res = client.get(
        "/api/avatar/status",
        headers={"Authorization": "Bearer garbage.token.here"},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/avatar/status — authenticated, various states
# ---------------------------------------------------------------------------

def test_status_pending(client, auth_headers):
    """Freshly-created user has pending status with no animal data."""
    res = client.get("/api/avatar/status", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["avatar_status"] == "pending"
    assert data["animal"] is None
    assert data["personality_traits"] is None
    assert data["avatar_description"] is None


def test_status_ready_with_full_data(client, db, auth_headers, test_user):
    """When avatar is ready, all generated fields are returned."""
    test_user.avatar_status = AvatarStatus.ready
    test_user.animal = "wolf"
    test_user.personality_traits = ["loyal", "fierce", "protective"]
    test_user.avatar_description = "A silver wolf-human hybrid with piercing amber eyes."
    db.commit()

    res = client.get("/api/avatar/status", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["avatar_status"] == "ready"
    assert data["animal"] == "wolf"
    assert data["personality_traits"] == ["loyal", "fierce", "protective"]
    assert "wolf-human hybrid" in data["avatar_description"]


def test_status_failed(client, db, auth_headers, test_user):
    test_user.avatar_status = AvatarStatus.failed
    db.commit()

    res = client.get("/api/avatar/status", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["avatar_status"] == "failed"
    assert res.json()["animal"] is None


def test_status_ready_no_traits(client, db, auth_headers, test_user):
    """Ready state with animal but no traits (e.g. old row before migration)."""
    test_user.avatar_status = AvatarStatus.ready
    test_user.animal = "fox"
    test_user.personality_traits = None
    test_user.avatar_description = None
    db.commit()

    res = client.get("/api/avatar/status", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["animal"] == "fox"
    assert data["personality_traits"] is None
    assert data["avatar_description"] is None


def test_status_includes_avatar_status_updated_at_field(client, auth_headers):
    """GET /status always includes avatar_status_updated_at (null when unset)."""
    res = client.get("/api/avatar/status", headers=auth_headers)
    assert res.status_code == 200
    assert "avatar_status_updated_at" in res.json()


def test_status_returns_avatar_status_updated_at_when_set(client, db, auth_headers, test_user):
    """avatar_status_updated_at is returned when the field has a value."""
    now = datetime.now(timezone.utc)
    test_user.avatar_status_updated_at = now
    db.commit()

    res = client.get("/api/avatar/status", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["avatar_status_updated_at"] is not None


# ---------------------------------------------------------------------------
# POST /api/avatar/regenerate — unauthenticated
# ---------------------------------------------------------------------------

def test_regenerate_unauthenticated(client):
    res = client.post("/api/avatar/regenerate")
    assert res.status_code == 401


def test_regenerate_invalid_token(client):
    res = client.post(
        "/api/avatar/regenerate",
        headers={"Authorization": "Bearer garbage.token.here"},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/avatar/regenerate — no bio
# ---------------------------------------------------------------------------

def test_regenerate_no_bio_returns_400(client, auth_headers):
    """User without a bio cannot regenerate — meaningful error returned."""
    res = client.post("/api/avatar/regenerate", headers=auth_headers)
    assert res.status_code == 400
    assert "bio" in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /api/avatar/regenerate — happy path
# ---------------------------------------------------------------------------

def test_regenerate_resets_avatar_to_pending(client, db, auth_headers, test_user):
    """Regenerate clears avatar data and returns pending status."""
    test_user.bio = "A curious fox who loves exploring dense forests at dusk."
    test_user.animal = "fox"
    test_user.personality_traits = ["clever", "curious"]
    test_user.avatar_description = "A rust-furred fox-human hybrid."
    test_user.avatar_status = AvatarStatus.pending
    db.commit()

    res = client.post("/api/avatar/regenerate", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["avatar_status"] == "pending"
    assert data["animal"] is None
    assert data["personality_traits"] is None
    assert data["avatar_description"] is None


def test_regenerate_queues_task(client, db, auth_headers, test_user, monkeypatch):
    """Regenerate calls generate_avatar.delay with the user's id."""
    test_user.bio = "A wise owl who reads books by moonlight in old libraries."
    db.commit()

    called_with = []
    monkeypatch.setattr(
        "app.api.avatar.generate_avatar.delay",
        lambda user_id: called_with.append(user_id),
    )

    res = client.post("/api/avatar/regenerate", headers=auth_headers)
    assert res.status_code == 200
    assert len(called_with) == 1
    assert called_with[0] == test_user.id


def test_regenerate_sets_avatar_status_updated_at(client, db, auth_headers, test_user):
    """Regenerate stamps avatar_status_updated_at so stale detection works."""
    test_user.bio = "A noble lion who leads the pride with quiet confidence."
    db.commit()

    res = client.post("/api/avatar/regenerate", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["avatar_status_updated_at"] is not None


def test_regenerate_from_ready_state_clears_all_avatar_data(client, db, auth_headers, test_user):
    """Regenerating from a ready avatar resets all fields."""
    test_user.bio = "A stealthy panther who moves silently through city streets."
    test_user.animal = "panther"
    test_user.personality_traits = ["stealthy", "focused"]
    test_user.avatar_description = "A dark panther-human hybrid with silver eyes."
    test_user.avatar_status = AvatarStatus.ready
    db.commit()

    res = client.post("/api/avatar/regenerate", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["avatar_status"] == "pending"
    assert data["animal"] is None
    assert data["personality_traits"] is None
    assert data["avatar_description"] is None


def test_regenerate_is_idempotent(client, db, auth_headers, test_user):
    """Calling regenerate multiple times never errors."""
    test_user.bio = "A playful otter who loves rivers and solving puzzles."
    db.commit()

    for _ in range(3):
        res = client.post("/api/avatar/regenerate", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["avatar_status"] == "pending"
