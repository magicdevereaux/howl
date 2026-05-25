"""
Tests for the edit/save flow auto-regeneration logic and the profile_needs_regen flag.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.user import AvatarStatus, User
from app.security import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_celery(monkeypatch):
    """Prevent actual Celery calls in every test."""
    monkeypatch.setattr("app.api.profile.generate_avatar.delay", lambda *_: None)
    monkeypatch.setattr("app.api.avatar.generate_avatar.delay", lambda *_: None)


def _make_user(db, *, email: str, bio: str = "A lone wolf who howls at the moon.", is_premium: bool = False, **kwargs) -> User:
    user = User(
        email=email,
        password_hash=hash_password("testpass"),
        avatar_status=AvatarStatus.ready,
        bio=bio,
        is_premium=is_premium,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _h(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _patch_bio(client, user, new_bio="My completely new bio that is different from the old one."):
    return client.patch("/api/profile/me", headers=_h(user), json={"bio": new_bio})


# ---------------------------------------------------------------------------
# Auto-regeneration when regen slot is available
# ---------------------------------------------------------------------------

def test_bio_change_triggers_regen_when_slot_available(client, db):
    """A bio change consumes one regen slot and queues generation."""
    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        user = _make_user(db, email="regen_ok@howl.app")
        res = _patch_bio(client, user)

    assert res.status_code == 200
    assert len(called) == 1
    db.refresh(user)
    assert user.avatar_status == AvatarStatus.pending
    assert user.profile_needs_regen is False


def test_bio_change_increments_regen_counter(client, db):
    user = _make_user(db, email="counter@howl.app")
    assert user.avatar_regenerations_this_month == 0

    _patch_bio(client, user)

    db.refresh(user)
    assert user.avatar_regenerations_this_month == 1


def test_unchanged_bio_does_not_trigger_regen(client, db):
    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        user = _make_user(db, email="same_bio@howl.app", bio="My bio.")
        # Send the same bio — should be a no-op for regen
        client.patch("/api/profile/me", headers=_h(user), json={"bio": "My bio."})

    assert called == []
    db.refresh(user)
    assert user.avatar_regenerations_this_month == 0
    assert user.profile_needs_regen is False


def test_non_bio_change_does_not_trigger_regen(client, db):
    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        user = _make_user(db, email="name_only@howl.app")
        client.patch("/api/profile/me", headers=_h(user), json={"name": "Jordan"})

    assert called == []
    db.refresh(user)
    assert user.avatar_regenerations_this_month == 0


# ---------------------------------------------------------------------------
# profile_needs_regen flag when no slot is available
# ---------------------------------------------------------------------------

def test_bio_change_sets_flag_when_no_slot(client, db):
    """When the monthly regen limit is exhausted, bio change sets profile_needs_regen."""
    from app.api.avatar import _MONTHLY_REGEN_LIMIT
    user = _make_user(db, email="noslot@howl.app")
    user.avatar_regenerations_this_month = _MONTHLY_REGEN_LIMIT
    user.regenerations_reset_at = datetime.now(timezone.utc) - timedelta(hours=10)
    db.commit()

    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        res = _patch_bio(client, user)

    assert res.status_code == 200
    assert called == []  # no task queued
    db.refresh(user)
    assert user.profile_needs_regen is True


def test_avatar_not_reset_when_no_regen_slot(client, db):
    """When the flag is set, the old avatar data is preserved (not reset to pending)."""
    from app.api.avatar import _MONTHLY_REGEN_LIMIT
    user = _make_user(db, email="keepavatar@howl.app", bio="Old bio.")
    user.animal = "wolf"
    user.avatar_regenerations_this_month = _MONTHLY_REGEN_LIMIT
    user.regenerations_reset_at = datetime.now(timezone.utc) - timedelta(hours=10)
    db.commit()

    _patch_bio(client, user, "Brand new bio that is completely different from before.")

    db.refresh(user)
    assert user.animal == "wolf"   # preserved
    assert user.avatar_status == AvatarStatus.ready   # not reset to pending


def test_flag_not_set_when_regen_available(client, db):
    user = _make_user(db, email="flagoff@howl.app")
    _patch_bio(client, user)
    db.refresh(user)
    assert user.profile_needs_regen is False


# ---------------------------------------------------------------------------
# Premium bypass
# ---------------------------------------------------------------------------

def test_premium_user_always_regens(client, db):
    from app.api.avatar import _MONTHLY_REGEN_LIMIT
    user = _make_user(db, email="prem_regen@howl.app", is_premium=True)
    user.avatar_regenerations_this_month = _MONTHLY_REGEN_LIMIT + 5
    user.regenerations_reset_at = datetime.now(timezone.utc) - timedelta(hours=5)
    db.commit()

    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        res = _patch_bio(client, user)

    assert res.status_code == 200
    assert len(called) == 1
    db.refresh(user)
    assert user.profile_needs_regen is False
    assert user.avatar_regenerations_this_month == _MONTHLY_REGEN_LIMIT + 5  # unchanged for premium


def test_premium_counter_not_incremented(client, db):
    user = _make_user(db, email="prem_count@howl.app", is_premium=True)
    assert user.avatar_regenerations_this_month == 0

    _patch_bio(client, user)

    db.refresh(user)
    assert user.avatar_regenerations_this_month == 0


# ---------------------------------------------------------------------------
# Manual regeneration clears the flag
# ---------------------------------------------------------------------------

def test_manual_regen_clears_profile_needs_regen(client, db):
    user = _make_user(db, email="clearflag@howl.app")
    user.profile_needs_regen = True
    db.commit()

    res = client.post("/api/avatar/regenerate", headers=_h(user))
    assert res.status_code == 200
    db.refresh(user)
    assert user.profile_needs_regen is False


def test_flag_visible_in_user_out(client, db):
    """profile_needs_regen is exposed in UserOut so the frontend can render the badge."""
    from app.api.avatar import _MONTHLY_REGEN_LIMIT
    user = _make_user(db, email="flagout@howl.app")
    user.profile_needs_regen = True
    db.commit()

    res = client.get("/api/profile/me", headers=_h(user))
    assert res.status_code == 200
    assert res.json()["profile_needs_regen"] is True


# ---------------------------------------------------------------------------
# 30-day window reset still works through the profile endpoint
# ---------------------------------------------------------------------------

def test_bio_change_resets_counter_after_window_expires(client, db):
    from app.api.avatar import _MONTHLY_REGEN_LIMIT
    user = _make_user(db, email="winreset@howl.app")
    user.avatar_regenerations_this_month = _MONTHLY_REGEN_LIMIT
    user.regenerations_reset_at = datetime.now(timezone.utc) - timedelta(days=31)
    db.commit()

    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        res = _patch_bio(client, user)

    assert res.status_code == 200
    assert len(called) == 1   # window expired → slot granted
    db.refresh(user)
    assert user.avatar_regenerations_this_month == 1
    assert user.profile_needs_regen is False
