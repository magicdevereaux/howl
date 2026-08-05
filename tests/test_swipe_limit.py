"""Tests for the daily swipe limit feature."""

from datetime import UTC, datetime, timedelta

from app.api.swipes import _DAILY_SWIPE_LIMIT
from app.models.user import AvatarStatus, User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, *, email: str, is_premium: bool = False, **kwargs) -> User:
    user = User(
        email=email,
        password_hash=hash_password("testpass"),
        avatar_status=AvatarStatus.ready,
        is_premium=is_premium,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _headers(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token(user.id)}"}


def _swipe(client, headers, target_id, direction="pass"):
    return client.post("/api/swipes", headers=headers, json={
        "target_user_id": target_id,
        "direction": direction,
    })


# ---------------------------------------------------------------------------
# Basic limit enforcement
# ---------------------------------------------------------------------------

def test_free_user_can_swipe_up_to_limit(client, db, test_user):
    targets = [_make_user(db, email=f"t{i}@howl.app") for i in range(_DAILY_SWIPE_LIMIT)]
    for t in targets:
        res = _swipe(client, _headers(test_user), t.id)
        assert res.status_code == 200, f"swipe on {t.email} failed: {res.json()}"


def test_free_user_blocked_on_swipe_beyond_limit(client, db, test_user):
    targets = [_make_user(db, email=f"b{i}@howl.app") for i in range(_DAILY_SWIPE_LIMIT + 1)]
    for t in targets[:_DAILY_SWIPE_LIMIT]:
        _swipe(client, _headers(test_user), t.id)

    # The (limit+1)-th swipe should be rejected
    res = _swipe(client, _headers(test_user), targets[_DAILY_SWIPE_LIMIT].id)
    assert res.status_code == 429


def test_premium_user_can_swipe_beyond_limit(client, db):
    premium = _make_user(db, email="premium@howl.app", is_premium=True)
    targets = [_make_user(db, email=f"p{i}@howl.app") for i in range(_DAILY_SWIPE_LIMIT + 5)]
    for t in targets:
        res = _swipe(client, _headers(premium), t.id)
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

def test_429_response_has_structured_detail(client, db, test_user):
    targets = [_make_user(db, email=f"s{i}@howl.app") for i in range(_DAILY_SWIPE_LIMIT + 1)]
    for t in targets[:_DAILY_SWIPE_LIMIT]:
        _swipe(client, _headers(test_user), t.id)

    res = _swipe(client, _headers(test_user), targets[_DAILY_SWIPE_LIMIT].id)
    assert res.status_code == 429
    detail = res.json()["detail"]
    assert detail["code"] == "daily_limit_reached"
    assert str(_DAILY_SWIPE_LIMIT) in detail["message"]
    assert "resets_at" in detail
    assert detail["limit"] == _DAILY_SWIPE_LIMIT


# ---------------------------------------------------------------------------
# Counter persistence
# ---------------------------------------------------------------------------

def test_daily_swipes_increments_in_db(client, db, test_user):
    target = _make_user(db, email="count@howl.app")
    assert test_user.daily_swipes == 0

    _swipe(client, _headers(test_user), target.id)

    db.refresh(test_user)
    assert test_user.daily_swipes == 1


def test_daily_swipes_not_incremented_for_premium(client, db):
    premium = _make_user(db, email="nocount@howl.app", is_premium=True)
    target = _make_user(db, email="target_nc@howl.app")

    _swipe(client, _headers(premium), target.id)

    db.refresh(premium)
    assert premium.daily_swipes == 0


def test_duplicate_swipe_does_not_increment_counter(client, db, test_user):
    target = _make_user(db, email="dup@howl.app")
    _swipe(client, _headers(test_user), target.id)
    db.refresh(test_user)
    count_after_first = test_user.daily_swipes

    # Second swipe on same target returns 409 and must NOT increment
    res = _swipe(client, _headers(test_user), target.id)
    assert res.status_code == 409

    db.refresh(test_user)
    assert test_user.daily_swipes == count_after_first


# ---------------------------------------------------------------------------
# Window reset logic
# ---------------------------------------------------------------------------

def test_counter_resets_after_24h_window(client, db, test_user):
    """A user who exhausted their limit yesterday should be able to swipe again."""
    # Simulate a fully exhausted counter from 25 hours ago
    test_user.daily_swipes = _DAILY_SWIPE_LIMIT
    test_user.swipes_reset_at = datetime.now(UTC) - timedelta(hours=25)
    db.commit()

    target = _make_user(db, email="fresh@howl.app")
    res = _swipe(client, _headers(test_user), target.id)
    assert res.status_code == 200

    db.refresh(test_user)
    assert test_user.daily_swipes == 1  # reset to 0 then incremented once


def test_counter_does_not_reset_within_window(client, db, test_user):
    """If the window hasn't expired yet, the counter stays accumulated."""
    test_user.daily_swipes = _DAILY_SWIPE_LIMIT - 1
    test_user.swipes_reset_at = datetime.now(UTC) - timedelta(hours=10)
    db.commit()

    target = _make_user(db, email="within@howl.app")
    res = _swipe(client, _headers(test_user), target.id)
    assert res.status_code == 200

    db.refresh(test_user)
    assert test_user.daily_swipes == _DAILY_SWIPE_LIMIT


def test_counter_blocked_mid_window(client, db, test_user):
    """Hitting the limit within an active window is refused correctly."""
    test_user.daily_swipes = _DAILY_SWIPE_LIMIT
    test_user.swipes_reset_at = datetime.now(UTC) - timedelta(hours=10)
    db.commit()

    target = _make_user(db, email="mid@howl.app")
    res = _swipe(client, _headers(test_user), target.id)
    assert res.status_code == 429


def test_first_swipe_ever_sets_reset_timestamp(client, db, test_user):
    """swipes_reset_at is null for new users; the first swipe sets it."""
    assert test_user.swipes_reset_at is None

    target = _make_user(db, email="first@howl.app")
    _swipe(client, _headers(test_user), target.id)

    db.refresh(test_user)
    assert test_user.swipes_reset_at is not None
