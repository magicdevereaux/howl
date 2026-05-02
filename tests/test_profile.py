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


# ---------------------------------------------------------------------------
# Bio update side effects (avatar reset)
# ---------------------------------------------------------------------------

def test_update_bio_clears_personality_traits_and_description(client, db, auth_headers, test_user):
    """Bio update clears stale personality_traits and avatar_description in the DB."""
    test_user.animal = "wolf"
    test_user.personality_traits = ["loyal", "fierce"]
    test_user.avatar_description = "A silver wolf-human hybrid."
    test_user.avatar_status = AvatarStatus.ready
    db.commit()

    res = client.patch(
        "/api/profile/me",
        headers=auth_headers,
        json={"bio": "A lone wolf who loves midnight runs and howling at the moon."},
    )
    assert res.status_code == 200
    # HTTP response (UserOut) doesn't expose traits/description — check the DB row
    db.refresh(test_user)
    assert test_user.personality_traits is None
    assert test_user.avatar_description is None
    assert test_user.animal is None


def test_update_bio_sets_avatar_status_updated_at(client, db, auth_headers, test_user):
    """Bio update stamps avatar_status_updated_at so stale detection works."""
    res = client.patch(
        "/api/profile/me",
        headers=auth_headers,
        json={"bio": "A lone wolf who loves midnight runs and howling at the moon."},
    )
    assert res.status_code == 200
    db.refresh(test_user)
    assert test_user.avatar_status_updated_at is not None


# ---------------------------------------------------------------------------
# Name and location updates
# ---------------------------------------------------------------------------

def test_update_name_success(client, auth_headers):
    """Patching name updates it without touching avatar_status."""
    res = client.patch("/api/profile/me", headers=auth_headers, json={"name": "Jordan"})
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Jordan"
    # Name change must NOT reset the avatar
    assert data["avatar_status"] == "pending"


def test_update_location_success(client, auth_headers):
    """Patching location updates it without touching avatar_status."""
    res = client.patch("/api/profile/me", headers=auth_headers, json={"location": "Austin, TX"})
    assert res.status_code == 200
    data = res.json()
    assert data["location"] == "Austin, TX"
    assert data["avatar_status"] == "pending"


def test_update_name_and_location_together(client, auth_headers):
    """Name and location can be updated in the same request."""
    res = client.patch(
        "/api/profile/me",
        headers=auth_headers,
        json={"name": "Riley", "location": "Seattle, WA"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Riley"
    assert data["location"] == "Seattle, WA"


def test_update_name_too_long(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"name": "x" * 101})
    assert res.status_code == 422


def test_update_location_too_long(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"location": "x" * 101})
    assert res.status_code == 422


def test_update_name_strips_whitespace(client, auth_headers):
    """Leading/trailing whitespace is stripped from name."""
    res = client.patch("/api/profile/me", headers=auth_headers, json={"name": "  Casey  "})
    assert res.status_code == 200
    assert res.json()["name"] == "Casey"


def test_update_blank_name_is_ignored(client, db, auth_headers, test_user):
    """Sending a whitespace-only name leaves the existing name unchanged.

    The validator strips and nullifies blank strings, which the handler
    treats the same as 'field not provided' — so the existing value is kept.
    To explicitly clear a name, send JSON null.
    """
    test_user.name = "OldName"
    db.commit()

    res = client.patch("/api/profile/me", headers=auth_headers, json={"name": "   "})
    assert res.status_code == 200
    assert res.json()["name"] == "OldName"


def test_update_profile_with_all_fields(client, auth_headers, monkeypatch):
    """Sending name, location, and bio in one request saves all three."""
    called = []
    monkeypatch.setattr(
        "app.api.profile.generate_avatar.delay",
        lambda user_id: called.append(user_id),
    )
    res = client.patch(
        "/api/profile/me",
        headers=auth_headers,
        json={
            "name": "Morgan",
            "location": "Chicago, IL",
            "bio": "A bold lion who leads the pride with quiet confidence and warmth.",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Morgan"
    assert data["location"] == "Chicago, IL"
    assert data["bio"] == "A bold lion who leads the pride with quiet confidence and warmth."
    assert data["avatar_status"] == "pending"
    # Bio was present so task should have been queued
    assert len(called) == 1


# ---------------------------------------------------------------------------
# Age field
# ---------------------------------------------------------------------------

def test_update_age_success(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"age": 25})
    assert res.status_code == 200
    assert res.json()["age"] == 25


def test_update_age_minimum_accepted(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"age": 18})
    assert res.status_code == 200
    assert res.json()["age"] == 18


def test_update_age_below_18_rejected(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"age": 17})
    assert res.status_code == 422


def test_update_age_zero_rejected(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"age": 0})
    assert res.status_code == 422


def test_update_age_maximum_accepted(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"age": 120})
    assert res.status_code == 200
    assert res.json()["age"] == 120


def test_update_age_above_120_rejected(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"age": 121})
    assert res.status_code == 422


def test_update_age_null_is_noop(client, db, auth_headers, test_user):
    """Sending age=null leaves the existing age unchanged."""
    test_user.age = 30
    db.commit()
    res = client.patch("/api/profile/me", headers=auth_headers, json={"age": None})
    assert res.status_code == 200
    assert res.json()["age"] == 30


def test_age_exposed_on_get_profile(client, db, auth_headers, test_user):
    test_user.age = 42
    db.commit()
    res = client.get("/api/profile/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["age"] == 42


def test_age_null_by_default(client, auth_headers):
    res = client.get("/api/profile/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["age"] is None


def test_age_does_not_trigger_avatar_reset(client, db, auth_headers, test_user):
    """Updating only age must not touch avatar_status."""
    from app.models.user import AvatarStatus
    test_user.avatar_status = AvatarStatus.ready
    test_user.animal = "fox"
    db.commit()
    res = client.patch("/api/profile/me", headers=auth_headers, json={"age": 28})
    assert res.status_code == 200
    assert res.json()["avatar_status"] == "ready"


def test_name_location_without_bio_does_not_trigger_avatar(client, db, auth_headers, test_user):
    """Updating only name/location never resets avatar_status or queues a task."""
    from app.models.user import AvatarStatus
    test_user.avatar_status = AvatarStatus.ready
    test_user.animal = "wolf"
    db.commit()

    called = []
    # Override the autouse mock to capture calls
    import app.api.profile as profile_module
    original = profile_module.generate_avatar.delay
    profile_module.generate_avatar.delay = lambda uid: called.append(uid)
    try:
        res = client.patch(
            "/api/profile/me",
            headers=auth_headers,
            json={"name": "Alex", "location": "Portland, OR"},
        )
    finally:
        profile_module.generate_avatar.delay = original

    assert res.status_code == 200
    assert res.json()["avatar_status"] == "ready"
    assert len(called) == 0
