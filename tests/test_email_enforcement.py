"""
Email-verification enforcement (GAPS #25).

Enforcement is *graduated*, which is the whole point of these tests:

- an unverified account keeps full access for
  ``settings.email_verification_grace_period_hours`` (default 72) measured from
  ``users.created_at``
- after that window the **outbound** actions close: swipe, swipe-undo, message
  send (REST and WebSocket), avatar generation
- every **read** stays open forever, plus resend-verification, logout, account
  deletion, push-token registration and profile edit -- so a user can see what
  they are about to lose and can still rescue themselves
- ``settings.enforce_email_verification`` is the operator kill switch

The 403 contract is pinned key-for-key by ``_assert_verification_403`` because
the web and mobile clients branch on it.
"""

from datetime import UTC, datetime, timedelta

import pytest
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.dependencies import (
    email_verification_error,
    email_verification_grace_expires_at,
)
from app.models.match import Match
from app.models.message import Message
from app.models.swipe import Swipe, SwipeDirection
from app.models.user import AvatarStatus, User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_outbound(monkeypatch):
    """Suppress the fire-and-forget Celery calls these routes make on success.

    Only the *successful* paths reach them, so without this the "allowed"
    assertions would need a live broker. conftest already neutralises
    notify_new_match.
    """
    monkeypatch.setattr("app.api.chat.notify_new_message.delay", lambda *_: None)
    monkeypatch.setattr("app.api.avatar.generate_avatar.delay", lambda *_: None)
    monkeypatch.setattr("app.api.profile.generate_avatar.delay", lambda *_: None)


@pytest.fixture()
def _ws_db(db, monkeypatch):
    """Wire the WebSocket handler's SessionLocal() to the test SQLite session."""
    monkeypatch.setattr("app.api.chat.SessionLocal", lambda: db)


def _past_grace() -> datetime:
    """A created_at old enough that any sane grace window has closed."""
    return datetime.now(UTC) - timedelta(days=100)


def _inside_grace() -> datetime:
    """A created_at comfortably inside the default 72-hour window."""
    return datetime.now(UTC) - timedelta(hours=1)


def _make_user(db, *, email: str, verified: bool = False, created_at=None, **kwargs) -> User:
    kwargs.setdefault("animal", "wolf")
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        avatar_status=AvatarStatus.ready,
        # A bio is required for POST /api/avatar/regenerate to get far enough to
        # be refused for the right reason rather than a 400.
        bio=kwargs.pop("bio", "A lone wolf who howls at the moon and means it."),
        is_email_verified=verified,
        created_at=created_at if created_at is not None else datetime.now(UTC),
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_match(db, a: User, b: User) -> Match:
    match = Match(user1_id=min(a.id, b.id), user2_id=max(a.id, b.id))
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


def _h(user: User) -> dict[str, str]:
    return {"Cookie": f"access_token={create_access_token(user.id)}"}


class _NoCloseSession:
    """Proxy a Session but ignore close().

    Both scripts under test own their session's lifecycle and close it in a
    `finally`. Handed the test session directly that would expunge every
    instance, so assertions afterwards raise "not persistent within this
    Session". The `db` fixture owns this session, so close() is not ours to call.
    """

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        return None


def _assert_verification_403(res, *, route: str) -> None:
    """Pin the 403 contract exactly. Both clients branch on this shape."""
    assert res.status_code == 403, f"{route}: expected 403, got {res.status_code} {res.text}"

    detail = res.json()["detail"]
    assert isinstance(detail, dict), f"{route}: detail must be an object, got {type(detail)}"

    # Exact key set — an extra or renamed key is a client-breaking change.
    assert set(detail) == {"code", "message", "grace_expired_at"}, (
        f"{route}: unexpected detail keys {sorted(detail)}"
    )
    assert detail["code"] == "email_verification_required"
    assert isinstance(detail["message"], str) and detail["message"].strip()

    # grace_expired_at must be ISO-8601 and unambiguous (offset-aware), or a
    # client cannot render "you lost access at ...' in local time.
    expired_at = datetime.fromisoformat(detail["grace_expired_at"])
    assert expired_at.tzinfo is not None, f"{route}: grace_expired_at lacks an offset"
    assert expired_at < datetime.now(UTC), f"{route}: grace_expired_at should be in the past"


# ---------------------------------------------------------------------------
# The gated routes, as callables, so every state can be swept over all of them.
# ---------------------------------------------------------------------------


def _call_swipe(client, user, db):
    target = _make_user(db, email=f"swipe_target_{user.id}@howl.app")
    return client.post(
        "/api/swipes",
        headers=_h(user),
        json={"target_user_id": target.id, "direction": "pass"},
    )


def _call_undo(client, user, db):
    target = _make_user(db, email=f"undo_target_{user.id}@howl.app")
    db.add(
        Swipe(user_id=user.id, target_user_id=target.id, direction=SwipeDirection.pass_)
    )
    db.commit()
    return client.delete("/api/swipes/last", headers=_h(user))


def _call_send_message(client, user, db):
    peer = _make_user(db, email=f"msg_peer_{user.id}@howl.app")
    match = _make_match(db, user, peer)
    return client.post(
        f"/api/matches/{match.id}/messages",
        headers=_h(user),
        json={"content": "Hello, is this thing on?"},
    )


def _call_regenerate(client, user, db):
    return client.post("/api/avatar/regenerate", headers=_h(user))


#: (label, callable, expected status when allowed)
GATED_ROUTES = [
    ("POST /api/swipes", _call_swipe, 200),
    ("DELETE /api/swipes/last", _call_undo, 200),
    ("POST /api/matches/{id}/messages", _call_send_message, 201),
    ("POST /api/avatar/regenerate", _call_regenerate, 200),
]

_GATED_IDS = [label for label, _fn, _ok in GATED_ROUTES]


# ---------------------------------------------------------------------------
# Unverified, inside the grace window → everything still works
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,call,ok_status", GATED_ROUTES, ids=_GATED_IDS)
def test_unverified_inside_grace_is_allowed(client, db, label, call, ok_status):
    """A brand-new account is fully usable. This is what makes enforcement safe."""
    user = _make_user(db, email="grace_ok@howl.app", verified=False, created_at=_inside_grace())

    res = call(client, user, db)

    assert res.status_code == ok_status, f"{label}: {res.status_code} {res.text}"


def test_a_just_registered_account_is_inside_grace(client, db):
    """created_at == now must be inside the window, not on the wrong side of it."""
    user = _make_user(db, email="brandnew@howl.app", verified=False, created_at=datetime.now(UTC))
    assert email_verification_error(user) is None


# ---------------------------------------------------------------------------
# Unverified, past the grace window → 403 on every gated route
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,call,ok_status", GATED_ROUTES, ids=_GATED_IDS)
def test_unverified_past_grace_is_refused(client, db, label, call, ok_status):
    user = _make_user(db, email="expired@howl.app", verified=False, created_at=_past_grace())

    res = call(client, user, db)

    _assert_verification_403(res, route=label)


def test_refusal_happens_before_any_write(client, db):
    """The 403 must be a gate, not a rollback: no swipe row may be left behind."""
    user = _make_user(db, email="nowrite@howl.app", verified=False, created_at=_past_grace())
    target = _make_user(db, email="nowrite_target@howl.app")

    res = client.post(
        "/api/swipes",
        headers=_h(user),
        json={"target_user_id": target.id, "direction": "like"},
    )

    assert res.status_code == 403
    assert db.query(Swipe).filter(Swipe.user_id == user.id).count() == 0
    assert db.query(Match).count() == 0


def test_refused_regeneration_does_not_touch_the_avatar(client, db):
    """A refused regen must not clear avatar data or spend a monthly slot."""
    user = _make_user(
        db, email="keepavatar@howl.app", verified=False, created_at=_past_grace()
    )
    user.animal = "wolf"
    user.avatar_url = "https://example.test/wolf.png"
    db.commit()

    res = client.post("/api/avatar/regenerate", headers=_h(user))

    assert res.status_code == 403
    db.refresh(user)
    assert user.animal == "wolf"
    assert user.avatar_url == "https://example.test/wolf.png"
    assert user.avatar_status == AvatarStatus.ready
    assert user.avatar_regenerations_this_month == 0


# ---------------------------------------------------------------------------
# Verified, past the grace window → unaffected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,call,ok_status", GATED_ROUTES, ids=_GATED_IDS)
def test_verified_past_grace_is_allowed(client, db, label, call, ok_status):
    """Verification, not age, is what matters once you have verified."""
    user = _make_user(db, email="verified_old@howl.app", verified=True, created_at=_past_grace())

    res = call(client, user, db)

    assert res.status_code == ok_status, f"{label}: {res.status_code} {res.text}"


# ---------------------------------------------------------------------------
# The kill switch (settings.enforce_email_verification = False)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label,call,ok_status", GATED_ROUTES, ids=_GATED_IDS)
def test_kill_switch_reopens_every_gated_route(
    client, db, monkeypatch, label, call, ok_status
):
    """GAPS #3 (no email provider) is why this escape hatch has to keep working."""
    monkeypatch.setattr(settings, "enforce_email_verification", False)

    user = _make_user(db, email="killswitch@howl.app", verified=False, created_at=_past_grace())

    res = call(client, user, db)

    assert res.status_code == ok_status, f"{label}: {res.status_code} {res.text}"


def test_kill_switch_is_read_at_call_time_not_import_time(db):
    """Flipping the setting must take effect without re-importing the module."""
    user = _make_user(db, email="latebind@howl.app", verified=False, created_at=_past_grace())

    assert email_verification_error(user) is not None  # enforced by default

    original = settings.enforce_email_verification
    try:
        settings.enforce_email_verification = False
        assert email_verification_error(user) is None
    finally:
        settings.enforce_email_verification = original

    assert email_verification_error(user) is not None


def test_enforcement_defaults_to_on():
    """The correct posture. The grace window is what makes it survivable."""
    assert settings.enforce_email_verification is True
    assert settings.email_verification_grace_period_hours == 72


# ---------------------------------------------------------------------------
# The naive-vs-aware created_at comparison
#
# `users.created_at` is DateTime(timezone=True) with a Python-side default, and
# SQLite -- the entire test suite -- hands it back NAIVE. These tests are built
# on detached User instances with the tzinfo set explicitly, rather than on
# whatever the driver happens to return, so they keep testing the normalisation
# itself even if the column type later starts guaranteeing aware values.
#
# Delete `_as_utc` from app/dependencies.py and both of these fail.
# ---------------------------------------------------------------------------


def test_grace_window_handles_a_naive_created_at():
    """Without normalisation this raises TypeError comparing naive to aware."""
    user = User(email="naive@howl.app", password_hash="x", is_email_verified=False)
    user.created_at = datetime(2020, 1, 1, 12, 0, 0)  # naive, as SQLite returns
    assert user.created_at.tzinfo is None  # precondition of this test

    expires_at = email_verification_grace_expires_at(user)
    assert expires_at.tzinfo is not None, "grace expiry must be offset-aware"

    # The real regression: this comparison is what blows up unnormalised.
    error = email_verification_error(user)
    assert error is not None
    assert error["code"] == "email_verification_required"


def test_naive_created_at_is_interpreted_as_utc_not_local_time():
    """Pins *which* timezone a naive value means.

    Every timestamp in this app is stored as UTC, so a naive read is UTC. A
    "fix" using `.astimezone()` would reinterpret it in the server's local zone
    and silently shift the grace window by the UTC offset -- on a UTC+13 host
    that is over half a day of wrongly granted or wrongly denied access.
    """
    naive = datetime(2020, 6, 1, 12, 0, 0)
    aware = naive.replace(tzinfo=UTC)

    naive_user = User(email="n@howl.app", password_hash="x", is_email_verified=False)
    naive_user.created_at = naive
    aware_user = User(email="a@howl.app", password_hash="x", is_email_verified=False)
    aware_user.created_at = aware

    assert email_verification_grace_expires_at(naive_user) == (
        email_verification_grace_expires_at(aware_user)
    )


def test_grace_expiry_is_created_at_plus_the_configured_window():
    user = User(email="w@howl.app", password_hash="x", is_email_verified=False)
    user.created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    expected = user.created_at + timedelta(
        hours=settings.email_verification_grace_period_hours
    )
    assert email_verification_grace_expires_at(user) == expected


def test_a_missing_created_at_is_treated_as_brand_new(db):
    """A data oddity must not instantly lock someone out."""
    user = User(email="nocreated@howl.app", password_hash="x", is_email_verified=False)
    user.created_at = None

    assert email_verification_error(user) is None


def test_grace_period_setting_is_honoured(db, monkeypatch):
    """Shrinking the window retroactively re-evaluates existing accounts."""
    user = _make_user(
        db,
        email="window@howl.app",
        verified=False,
        created_at=datetime.now(UTC) - timedelta(hours=10),
    )

    monkeypatch.setattr(settings, "email_verification_grace_period_hours", 72)
    assert email_verification_error(user) is None  # 10h < 72h

    monkeypatch.setattr(settings, "email_verification_grace_period_hours", 5)
    assert email_verification_error(user) is not None  # 10h > 5h


# ---------------------------------------------------------------------------
# Ungated routes stay open for a past-grace unverified user
#
# The product rule: they must be able to see what they are about to lose, and
# must be able to fix a typo'd email address.
# ---------------------------------------------------------------------------


def test_discover_read_stays_open(client, db):
    user = _make_user(db, email="ungated_discover@howl.app", created_at=_past_grace())
    res = client.get("/api/users/discover", headers=_h(user))
    assert res.status_code == 200


def test_matches_read_stays_open(client, db):
    user = _make_user(db, email="ungated_matches@howl.app", created_at=_past_grace())
    peer = _make_user(db, email="ungated_matches_peer@howl.app")
    _make_match(db, user, peer)

    res = client.get("/api/users/matches", headers=_h(user))
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_message_history_read_stays_open(client, db):
    """They must be able to read the conversation they can no longer reply to."""
    user = _make_user(db, email="ungated_history@howl.app", created_at=_past_grace())
    peer = _make_user(db, email="ungated_history_peer@howl.app")
    match = _make_match(db, user, peer)
    db.add(Message(match_id=match.id, sender_id=peer.id, content="Are you there?"))
    db.commit()

    res = client.get(f"/api/matches/{match.id}/messages", headers=_h(user))
    assert res.status_code == 200
    assert [m["content"] for m in res.json()["messages"]] == ["Are you there?"]


def test_unread_count_stays_open(client, db):
    user = _make_user(db, email="ungated_unread@howl.app", created_at=_past_grace())
    peer = _make_user(db, email="ungated_unread_peer@howl.app")
    match = _make_match(db, user, peer)

    res = client.get(f"/api/matches/{match.id}/unread-count", headers=_h(user))
    assert res.status_code == 200


def test_resend_verification_stays_open(client, db):
    """The only self-rescue path -- gating it would be a deadlock."""
    _make_user(db, email="ungated_resend@howl.app", created_at=_past_grace())
    res = client.post(
        "/api/auth/resend-verification", json={"email": "ungated_resend@howl.app"}
    )
    assert res.status_code == 200


def test_mobile_resend_verification_stays_open(client, db):
    _make_user(db, email="ungated_resend_m@howl.app", created_at=_past_grace())
    res = client.post(
        "/api/mobile/auth/resend-verification", json={"email": "ungated_resend_m@howl.app"}
    )
    assert res.status_code == 200


def test_profile_read_and_edit_stay_open(client, db):
    """Editing must stay open; it is adjacent to fixing a typo'd email."""
    user = _make_user(db, email="ungated_profile@howl.app", created_at=_past_grace())

    assert client.get("/api/profile/me", headers=_h(user)).status_code == 200

    res = client.patch("/api/profile/me", headers=_h(user), json={"name": "Renamed"})
    assert res.status_code == 200
    assert res.json()["name"] == "Renamed"


def test_avatar_status_read_stays_open(client, db):
    user = _make_user(db, email="ungated_avstatus@howl.app", created_at=_past_grace())
    assert client.get("/api/avatar/status", headers=_h(user)).status_code == 200


def test_logout_stays_open(client, db):
    user = _make_user(db, email="ungated_logout@howl.app", created_at=_past_grace())
    assert client.post("/api/auth/logout", headers=_h(user)).status_code == 204


def test_push_token_registration_stays_open(client, db):
    """Gating this would stop the very notification that says 'please verify'."""
    user = _make_user(db, email="ungated_push@howl.app", created_at=_past_grace())
    res = client.post(
        "/api/push-tokens", headers=_h(user), json={"token": "ExponentPushToken[abc123]"}
    )
    assert res.status_code == 204


def test_account_deletion_stays_open(client, db):
    """Never trap a user in an account they cannot leave."""
    user = _make_user(db, email="ungated_delete@howl.app", created_at=_past_grace())
    res = client.delete("/api/profile/me", headers=_h(user))
    assert res.status_code == 204
    assert db.get(User, user.id) is None


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


def test_ws_refuses_unverified_past_grace_with_error_frame_and_4403(client, db, _ws_db):
    """Refused loudly: a structured frame carrying the same `code`, then a close.

    A silent drop would leave the client unable to explain the failure.
    """
    user = _make_user(db, email="ws_expired@howl.app", verified=False, created_at=_past_grace())
    peer = _make_user(db, email="ws_expired_peer@howl.app")
    match = _make_match(db, user, peer)
    token = create_access_token(user.id)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/matches/{match.id}/ws?token={token}") as ws:
            frame = ws.receive_json()
            assert frame["type"] == "error"
            assert frame["error"]["code"] == "email_verification_required"
            assert set(frame["error"]) == {"code", "message", "grace_expired_at"}
            ws.receive_json()  # server has closed by now

    assert exc_info.value.code == 4403


def test_ws_allows_unverified_inside_grace(client, db, _ws_db):
    user = _make_user(db, email="ws_grace@howl.app", verified=False, created_at=_inside_grace())
    peer = _make_user(db, email="ws_grace_peer@howl.app")
    match = _make_match(db, user, peer)
    token = create_access_token(user.id)

    with client.websocket_connect(f"/api/matches/{match.id}/ws?token={token}"):
        pass  # accepted and closed cleanly


def test_ws_allows_verified_past_grace(client, db, _ws_db):
    user = _make_user(db, email="ws_verified@howl.app", verified=True, created_at=_past_grace())
    peer = _make_user(db, email="ws_verified_peer@howl.app")
    match = _make_match(db, user, peer)
    token = create_access_token(user.id)

    with client.websocket_connect(f"/api/matches/{match.id}/ws?token={token}"):
        pass


def test_ws_non_member_still_gets_4003_regardless_of_verification(client, db, _ws_db):
    """Authorisation is checked before verification, deliberately.

    Probing a match you are not part of must not reveal anything about your own
    account state -- and must not report the wrong reason for the refusal.
    """
    outsider = _make_user(
        db, email="ws_outsider@howl.app", verified=False, created_at=_past_grace()
    )
    a = _make_user(db, email="ws_member_a@howl.app")
    b = _make_user(db, email="ws_member_b@howl.app")
    match = _make_match(db, a, b)
    token = create_access_token(outsider.id)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"/api/matches/{match.id}/ws?token={token}") as ws:
            ws.receive_json()

    assert exc_info.value.code == 4003, "verification check ran before authorisation"


def test_ws_kill_switch_reopens_the_socket(client, db, _ws_db, monkeypatch):
    monkeypatch.setattr(settings, "enforce_email_verification", False)

    user = _make_user(db, email="ws_kill@howl.app", verified=False, created_at=_past_grace())
    peer = _make_user(db, email="ws_kill_peer@howl.app")
    match = _make_match(db, user, peer)
    token = create_access_token(user.id)

    with client.websocket_connect(f"/api/matches/{match.id}/ws?token={token}"):
        pass


# ---------------------------------------------------------------------------
# The dependency is actually wired where we intend
#
# Replaces test_require_verified_email_is_not_wired_to_any_route, which asserted
# the opposite while the rollout was still a product decision.
# ---------------------------------------------------------------------------


def test_require_verified_email_is_wired_to_exactly_the_intended_routes():
    """A refactor that silently drops -- or over-applies -- the gate fails here."""
    from app.dependencies import require_verified_email
    from app.main import app

    wired = set()
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        for dep in getattr(dependant, "dependencies", []) or []:
            if getattr(dep, "call", None) is require_verified_email:
                for method in sorted(getattr(route, "methods", set()) or {"WS"}):
                    wired.add(f"{method} {route.path}")

    assert wired == {
        "POST /api/swipes",
        "DELETE /api/swipes/last",
        "POST /api/matches/{match_id}/messages",
        "POST /api/avatar/regenerate",
    }, f"gated route set changed: {sorted(wired)}"


# ---------------------------------------------------------------------------
# scripts/backfill_email_verification.py
#
# Grandfathers in accounts that registered before enforcement existed, so
# turning it on does not retroactively strip them. Dry-run by default because
# it writes to the production users table.
# ---------------------------------------------------------------------------


def test_backfill_dry_run_changes_nothing(db):
    from scripts.backfill_email_verification import backfill

    old = _make_user(db, email="bf_old@howl.app", verified=False, created_at=_past_grace())

    scanned, changed = backfill(db, datetime.now(UTC), apply_changes=False)

    assert scanned == 1
    assert changed == 1  # it *reports* the work it would do
    db.refresh(old)
    assert old.is_email_verified is False, "dry run wrote to the database"


def test_backfill_apply_marks_pre_cutoff_accounts_verified(db):
    from scripts.backfill_email_verification import backfill

    old = _make_user(db, email="bf_a@howl.app", verified=False, created_at=_past_grace())

    scanned, changed = backfill(db, datetime.now(UTC), apply_changes=True)

    assert (scanned, changed) == (1, 1)
    db.refresh(old)
    assert old.is_email_verified is True
    # And the point of the whole exercise: they are no longer refused.
    assert email_verification_error(old) is None


def test_backfill_respects_the_cutoff(db):
    """Accounts created after the cutoff are what enforcement is *for*."""
    from scripts.backfill_email_verification import backfill

    cutoff = datetime.now(UTC) - timedelta(days=10)
    before = _make_user(
        db, email="bf_before@howl.app", verified=False,
        created_at=cutoff - timedelta(days=5),
    )
    after = _make_user(
        db, email="bf_after@howl.app", verified=False,
        created_at=cutoff + timedelta(days=5),
    )

    scanned, changed = backfill(db, cutoff, apply_changes=True)

    assert (scanned, changed) == (1, 1)
    db.refresh(before)
    db.refresh(after)
    assert before.is_email_verified is True
    assert after.is_email_verified is False, "an account newer than the cutoff was touched"


def test_backfill_is_idempotent(db):
    from scripts.backfill_email_verification import backfill

    _make_user(db, email="bf_idem@howl.app", verified=False, created_at=_past_grace())

    first = backfill(db, datetime.now(UTC), apply_changes=True)
    second = backfill(db, datetime.now(UTC), apply_changes=True)

    assert first[1] == 1
    assert second[1] == 0, "a second run reported changes it did not make"


def test_backfill_leaves_already_verified_accounts_alone(db):
    """`changed` must count rows actually updated, not rows scanned."""
    from scripts.backfill_email_verification import backfill

    _make_user(db, email="bf_v1@howl.app", verified=True, created_at=_past_grace())
    _make_user(db, email="bf_v2@howl.app", verified=True, created_at=_past_grace())
    _make_user(db, email="bf_u1@howl.app", verified=False, created_at=_past_grace())

    scanned, changed = backfill(db, datetime.now(UTC), apply_changes=True)

    assert scanned == 3
    assert changed == 1


def test_backfill_never_unverifies_anyone(db):
    from scripts.backfill_email_verification import backfill

    verified = _make_user(db, email="bf_keep@howl.app", verified=True, created_at=_past_grace())

    backfill(db, datetime.now(UTC), apply_changes=True)

    db.refresh(verified)
    assert verified.is_email_verified is True


def test_backfill_cutoff_parsing():
    """Naive input means UTC -- every timestamp in this app is stored as UTC."""
    from scripts.backfill_email_verification import parse_cutoff

    assert parse_cutoff("2026-08-08T00:00:00Z") == datetime(2026, 8, 8, tzinfo=UTC)
    assert parse_cutoff("2026-08-08T00:00:00") == datetime(2026, 8, 8, tzinfo=UTC)
    assert parse_cutoff("2026-08-08") == datetime(2026, 8, 8, tzinfo=UTC)
    # An explicit offset is respected and normalised to UTC.
    assert parse_cutoff("2026-08-08T02:00:00+02:00") == datetime(2026, 8, 8, tzinfo=UTC)


def test_backfill_cli_defaults_to_dry_run(db, monkeypatch, capsys):
    """--apply must be explicit: this writes to the production user table."""
    from scripts import backfill_email_verification as bf

    user = _make_user(db, email="bf_cli@howl.app", verified=False, created_at=_past_grace())
    monkeypatch.setattr(bf, "SessionLocal", lambda: _NoCloseSession(db))

    assert bf.main([]) == 0

    db.refresh(user)
    assert user.is_email_verified is False, "the default run wrote to the database"

    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "Would mark verified:            1" in out


def test_backfill_cli_apply_writes(db, monkeypatch, capsys):
    from scripts import backfill_email_verification as bf

    user = _make_user(db, email="bf_cli2@howl.app", verified=False, created_at=_past_grace())
    monkeypatch.setattr(bf, "SessionLocal", lambda: _NoCloseSession(db))

    assert bf.main(["--apply"]) == 0

    db.refresh(user)
    assert user.is_email_verified is True
    assert "APPLY" in capsys.readouterr().out


def test_backfill_cli_rejects_apply_with_dry_run(db, monkeypatch):
    from scripts import backfill_email_verification as bf

    monkeypatch.setattr(bf, "SessionLocal", lambda: _NoCloseSession(db))
    with pytest.raises(SystemExit):
        bf.main(["--apply", "--dry-run"])


# ---------------------------------------------------------------------------
# The seeded bots
# ---------------------------------------------------------------------------


def test_every_seeded_bot_is_email_verified(db, monkeypatch):
    """`scripts/seed_demo_users.py` sets is_email_verified=True. Pin it.

    The seed backdates `created_at` across the previous ~30 days, so every bot
    is far past any grace window. Verified is what keeps them exempt from
    enforcement.

    Precise scope, so this test is not read as promising more than it checks:
    the gate is HTTP-only, and bots act through Celery tasks
    (`auto_match_demo_user`, `bot_response`) that write to the database
    directly. Discover filters on `avatar_status`, not on verification. So
    unverified bots would not *by themselves* empty the discover queue -- this
    is defence in depth for anything that ever drives a bot through the API,
    and it keeps the demo's premise (1000 usable accounts) explicit.

    Runs the real `seed()` rather than string-matching the source, so it fails
    for a behavioural change however it is written.
    """
    from scripts import seed_demo_users

    monkeypatch.setattr(seed_demo_users, "SessionLocal", lambda: _NoCloseSession(db))

    seed_demo_users.seed()

    bots = db.query(User).filter(User.is_bot.is_(True)).all()
    assert len(bots) == len(seed_demo_users.DEMO_USERS) == 1000

    unverified = [b.email for b in bots if not b.is_email_verified]
    assert unverified == [], (
        f"{len(unverified)} seeded bot(s) are unverified, e.g. {unverified[:3]}"
    )

    # The invariant that actually matters: the gate never refuses a bot.
    assert [b.email for b in bots if email_verification_error(b) is not None] == []


def test_reads_are_not_gated_by_the_dependency():
    """Named reads must never acquire the gate, whatever else is refactored."""
    from app.dependencies import require_verified_email
    from app.main import app

    must_stay_open = {
        ("GET", "/api/users/discover"),
        ("GET", "/api/users/matches"),
        ("GET", "/api/matches/{match_id}/messages"),
        ("GET", "/api/matches/{match_id}/unread-count"),
        ("GET", "/api/profile/me"),
        ("PATCH", "/api/profile/me"),
        ("DELETE", "/api/profile/me"),
        ("GET", "/api/avatar/status"),
        ("POST", "/api/auth/resend-verification"),
        ("POST", "/api/mobile/auth/resend-verification"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/push-tokens"),
    }

    offenders = []
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        deps = getattr(dependant, "dependencies", []) or []
        if not any(getattr(d, "call", None) is require_verified_email for d in deps):
            continue
        for method in getattr(route, "methods", set()) or set():
            if (method, route.path) in must_stay_open:
                offenders.append(f"{method} {route.path}")

    assert offenders == [], f"these must stay ungated: {offenders}"
