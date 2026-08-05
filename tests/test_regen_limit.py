"""Tests for the monthly avatar regeneration limit."""

from datetime import UTC, datetime, timedelta

import pytest

from app.api.avatar import _MONTHLY_REGEN_LIMIT
from app.models.user import AvatarStatus, User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_generate(monkeypatch):
    """Prevent real Celery calls in all tests in this module."""
    monkeypatch.setattr("app.api.avatar.generate_avatar.delay", lambda *_: None)
    monkeypatch.setattr("app.api.profile.generate_avatar.delay", lambda *_: None)


def _make_user(db, *, email: str, is_premium: bool = False, bio: str = "A wolf who howls at the moon under the night sky.") -> User:
    user = User(
        email=email,
        password_hash=hash_password("testpass"),
        avatar_status=AvatarStatus.ready,
        bio=bio,
        is_premium=is_premium,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _h(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token(user.id)}"}


def _regen(client, user):
    return client.post("/api/avatar/regenerate", headers=_h(user))


# ---------------------------------------------------------------------------
# Basic limit enforcement
# ---------------------------------------------------------------------------

def test_free_user_can_regenerate_once(client, db):
    user = _make_user(db, email="once@howl.app")
    res = _regen(client, user)
    assert res.status_code == 200


def test_free_user_blocked_on_second_regeneration(client, db):
    user = _make_user(db, email="twice@howl.app")
    _regen(client, user)   # first: allowed
    res = _regen(client, user)  # second: blocked
    assert res.status_code == 429


def test_premium_user_can_regenerate_multiple_times(client, db):
    user = _make_user(db, email="prem@howl.app", is_premium=True)
    for _ in range(_MONTHLY_REGEN_LIMIT + 3):
        res = _regen(client, user)
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

def test_429_response_has_structured_detail(client, db):
    user = _make_user(db, email="shape@howl.app")
    _regen(client, user)
    res = _regen(client, user)
    assert res.status_code == 429
    detail = res.json()["detail"]
    assert detail["code"] == "regeneration_limit_reached"
    assert str(_MONTHLY_REGEN_LIMIT) in detail["message"]
    assert "resets_at" in detail
    assert detail["limit"] == _MONTHLY_REGEN_LIMIT


# ---------------------------------------------------------------------------
# Counter persistence
# ---------------------------------------------------------------------------

def test_counter_increments_after_manual_regeneration(client, db):
    user = _make_user(db, email="count@howl.app")
    assert user.avatar_regenerations_this_month == 0
    _regen(client, user)
    db.refresh(user)
    assert user.avatar_regenerations_this_month == 1


def test_premium_counter_stays_at_zero(client, db):
    user = _make_user(db, email="nocount@howl.app", is_premium=True)
    _regen(client, user)
    _regen(client, user)
    db.refresh(user)
    assert user.avatar_regenerations_this_month == 0


def test_bio_update_counts_against_shared_limit(client, db):
    """Bio changes via PATCH and manual regens share the same monthly quota.

    Previously bio changes bypassed the limit; now they consume a slot so
    users who save profile changes can't circumvent the regeneration cap.
    """
    user = _make_user(db, email="bio@howl.app")
    assert user.avatar_regenerations_this_month == 0

    # Bio update consumes the one free slot
    client.patch(
        "/api/profile/me",
        headers=_h(user),
        json={"bio": "A completely new bio that is long enough to trigger regeneration."},
    )

    db.refresh(user)
    assert user.avatar_regenerations_this_month == 1  # slot consumed

    # The manual regen is now blocked — quota exhausted
    res = _regen(client, user)
    assert res.status_code == 429


# ---------------------------------------------------------------------------
# 30-day window reset logic
# ---------------------------------------------------------------------------

def test_counter_resets_after_30_day_window(client, db):
    """A user who used their regeneration 31 days ago should get a fresh slot."""
    user = _make_user(db, email="reset@howl.app")
    user.avatar_regenerations_this_month = _MONTHLY_REGEN_LIMIT
    user.regenerations_reset_at = datetime.now(UTC) - timedelta(days=31)
    db.commit()

    res = _regen(client, user)
    assert res.status_code == 200

    db.refresh(user)
    assert user.avatar_regenerations_this_month == 1  # reset to 0, then incremented once


def test_counter_does_not_reset_within_window(client, db):
    """Within the 30-day window the accumulated count is preserved."""
    user = _make_user(db, email="notreset@howl.app")
    user.avatar_regenerations_this_month = _MONTHLY_REGEN_LIMIT - 1
    user.regenerations_reset_at = datetime.now(UTC) - timedelta(days=10)
    db.commit()

    res = _regen(client, user)
    assert res.status_code == 200

    db.refresh(user)
    assert user.avatar_regenerations_this_month == _MONTHLY_REGEN_LIMIT


def test_blocked_within_active_window(client, db):
    user = _make_user(db, email="blocked@howl.app")
    user.avatar_regenerations_this_month = _MONTHLY_REGEN_LIMIT
    user.regenerations_reset_at = datetime.now(UTC) - timedelta(days=10)
    db.commit()

    res = _regen(client, user)
    assert res.status_code == 429


def test_first_regeneration_sets_reset_timestamp(client, db):
    """regenerations_reset_at is null for new users; the first regeneration sets it."""
    user = _make_user(db, email="first@howl.app")
    assert user.regenerations_reset_at is None

    _regen(client, user)

    db.refresh(user)
    assert user.regenerations_reset_at is not None
