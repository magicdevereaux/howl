"""Tests for GET /api/avatar/status."""

from app.models.user import AvatarStatus


# ---------------------------------------------------------------------------
# Unauthenticated / bad-auth cases
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
# Authenticated — various avatar states
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
