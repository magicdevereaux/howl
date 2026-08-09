"""
Tests for the edit/save flow auto-regeneration logic and the profile_needs_regen flag.
"""

from datetime import UTC, datetime, timedelta
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
    # animal is defaulted because ck_users_ready_avatar_has_animal forbids
    # avatar_status='ready' with animal IS NULL — a state the pipeline can never
    # produce, so a ready fixture without one was never a realistic user.
    kwargs.setdefault("animal", "wolf")
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
    return {"Cookie": f"access_token={create_access_token(user.id)}"}


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
    user.regenerations_reset_at = datetime.now(UTC) - timedelta(hours=10)
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
    user.regenerations_reset_at = datetime.now(UTC) - timedelta(hours=10)
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
# Stale-pending refund on the shared counter (GAPS-ROUND-2 #40)
#
# The bio-edit path shares avatar_regenerations_this_month with
# POST /api/avatar/regenerate, so it has to share the refund. A user whose
# first avatar is stuck behind a dead worker must not be told their profile is
# permanently out of date.
# ---------------------------------------------------------------------------

def test_bio_edit_refunds_a_stale_pending_slot(client, db):
    from app.api.avatar import _MONTHLY_REGEN_LIMIT

    user = _make_user(db, email="bio_stuck@howl.app", bio="Old bio.")
    user.avatar_status = AvatarStatus.pending
    user.animal = None
    user.avatar_status_updated_at = datetime.now(UTC) - timedelta(minutes=10)
    user.avatar_regenerations_this_month = _MONTHLY_REGEN_LIMIT
    user.regenerations_reset_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()

    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        res = _patch_bio(client, user, "A brand new bio, quite unlike the previous one.")

    assert res.status_code == 200
    db.refresh(user)
    assert user.profile_needs_regen is False, "the stuck attempt was never refunded"
    assert user.avatar_regenerations_this_month == _MONTHLY_REGEN_LIMIT


def test_bio_edit_does_not_refund_a_fresh_pending_slot(client, db):
    from app.api.avatar import _MONTHLY_REGEN_LIMIT

    user = _make_user(db, email="bio_running@howl.app", bio="Old bio.")
    user.avatar_status = AvatarStatus.pending
    user.animal = None
    user.avatar_status_updated_at = datetime.now(UTC)
    user.avatar_regenerations_this_month = _MONTHLY_REGEN_LIMIT
    user.regenerations_reset_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()

    res = _patch_bio(client, user, "Another different bio for the running case.")

    assert res.status_code == 200
    db.refresh(user)
    assert user.profile_needs_regen is True


# ---------------------------------------------------------------------------
# Premium bypass
# ---------------------------------------------------------------------------

def test_premium_user_always_regens(client, db):
    from app.api.avatar import _MONTHLY_REGEN_LIMIT
    user = _make_user(db, email="prem_regen@howl.app", is_premium=True)
    user.avatar_regenerations_this_month = _MONTHLY_REGEN_LIMIT + 5
    user.regenerations_reset_at = datetime.now(UTC) - timedelta(hours=5)
    db.commit()

    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        res = _patch_bio(client, user)

    assert res.status_code == 200
    assert len(called) == 1
    db.refresh(user)
    assert user.profile_needs_regen is False
    # Premium shares the counter but against the far higher abuse ceiling.
    assert user.avatar_regenerations_this_month == _MONTHLY_REGEN_LIMIT + 6


def test_premium_bio_edit_counts_against_the_ceiling(client, db):
    """The bio-edit path must share the premium ceiling.

    If it did not, editing a bio repeatedly would be a trivial way around the
    limit on the explicit regenerate endpoint.
    """
    user = _make_user(db, email="prem_count@howl.app", is_premium=True)
    assert user.avatar_regenerations_this_month == 0

    _patch_bio(client, user)

    db.refresh(user)
    assert user.avatar_regenerations_this_month == 1


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
    user.regenerations_reset_at = datetime.now(UTC) - timedelta(days=31)
    db.commit()

    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        res = _patch_bio(client, user)

    assert res.status_code == 200
    assert len(called) == 1   # window expired → slot granted
    db.refresh(user)
    assert user.avatar_regenerations_this_month == 1
    assert user.profile_needs_regen is False


# ---------------------------------------------------------------------------
# Email-verification gate on the bio-edit regen path (GAPS #25)
#
# PATCH /api/profile/me stays open past the grace window -- a user has to be
# able to edit their profile, and it is adjacent to fixing a typo'd email -- but
# it must not spend a paid DALL-E call, or it becomes a walk-around for the gate
# on POST /api/avatar/regenerate.
# ---------------------------------------------------------------------------

def _past_grace() -> datetime:
    """A created_at old enough that any sane grace window has closed."""
    return datetime.now(UTC) - timedelta(days=100)


def test_bio_edit_withholds_regen_for_unverified_past_grace(client, db):
    """The bio saves, but the paid generation is withheld and deferred."""
    user = _make_user(
        db,
        email="unverified_regen@howl.app",
        bio="Old bio.",
        is_email_verified=False,
        created_at=_past_grace(),
    )
    user.animal = "wolf"
    db.commit()

    new_bio = "Brand new bio that is completely different from the old one."
    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        res = _patch_bio(client, user, new_bio)

    # The edit itself succeeds -- this endpoint is deliberately not gated.
    assert res.status_code == 200
    assert res.json()["bio"] == new_bio

    assert called == [], "an unverified past-grace account burned a paid DALL-E call"

    db.refresh(user)
    assert user.bio == new_bio               # the write landed
    assert user.profile_needs_regen is True  # deferred, not lost
    assert user.animal == "wolf"             # existing avatar preserved
    assert user.avatar_status == AvatarStatus.ready


def test_withheld_regen_does_not_consume_a_monthly_slot(client, db):
    """A withheld generation must not bill the user's quota for a missing image."""
    user = _make_user(
        db,
        email="unverified_slot@howl.app",
        bio="Old bio.",
        is_email_verified=False,
        created_at=_past_grace(),
    )

    _patch_bio(client, user, "A totally different bio than the one before it.")

    db.refresh(user)
    assert user.avatar_regenerations_this_month == 0, (
        "the gate consumed a regen slot for an image that was never generated"
    )


def test_bio_edit_still_regens_for_verified_past_grace(client, db):
    """Verified accounts are unaffected by the gate, however old they are."""
    user = _make_user(
        db,
        email="verified_regen@howl.app",
        bio="Old bio.",
        is_email_verified=True,
        created_at=_past_grace(),
    )

    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        res = _patch_bio(client, user, "A fresh bio, quite unlike the previous one.")

    assert res.status_code == 200
    assert called == [user.id]
    db.refresh(user)
    assert user.profile_needs_regen is False
    assert user.avatar_status == AvatarStatus.pending


def test_bio_edit_still_regens_for_unverified_inside_grace(client, db):
    """Inside the grace window an unverified account behaves completely normally."""
    user = _make_user(
        db,
        email="grace_regen@howl.app",
        bio="Old bio.",
        is_email_verified=False,
        created_at=datetime.now(UTC),
    )

    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        res = _patch_bio(client, user, "A brand new bio unlike the one it replaced.")

    assert res.status_code == 200
    assert called == [user.id]
    db.refresh(user)
    assert user.profile_needs_regen is False


def test_bio_edit_regens_past_grace_when_enforcement_is_off(client, db, monkeypatch):
    """The kill switch must reopen the spend path too, not just the 403 routes."""
    from app.config import settings

    monkeypatch.setattr(settings, "enforce_email_verification", False)

    user = _make_user(
        db,
        email="killswitch_regen@howl.app",
        bio="Old bio.",
        is_email_verified=False,
        created_at=_past_grace(),
    )

    called = []
    with patch("app.api.profile.generate_avatar.delay", lambda uid: called.append(uid)):
        res = _patch_bio(client, user, "Yet another entirely different bio string.")

    assert res.status_code == 200
    assert called == [user.id]
