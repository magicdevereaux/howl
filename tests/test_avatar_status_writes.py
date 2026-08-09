"""`avatar_status` and `avatar_status_updated_at` must move together (#41).

The timestamp had two writers, both at enqueue time, and the task that actually
moves the status never touched it. The clients apply a two-minute staleness rule
to it and *stop polling* when it fires, and since #40 the server reads it to
decide whether a charged regeneration is refundable -- so a timestamp that lags
its status is both a UI bug and a spend bug.
"""

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.models.user import AvatarStatus, User
from app.services.avatar_status import set_avatar_status
from app.tasks.avatar import _mark_failed, generate_avatar

APP_DIR = Path(__file__).resolve().parents[1] / "app"


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------

def test_set_avatar_status_writes_both_fields():
    user = MagicMock(spec=User)
    before = datetime.now(UTC)

    set_avatar_status(user, AvatarStatus.ready)

    assert user.avatar_status == AvatarStatus.ready
    assert user.avatar_status_updated_at >= before


def test_set_avatar_status_stamps_an_aware_utc_timestamp():
    """Naive timestamps here would silently compare wrong against the window."""
    user = MagicMock(spec=User)
    set_avatar_status(user, AvatarStatus.pending)
    assert user.avatar_status_updated_at.tzinfo is not None


# ---------------------------------------------------------------------------
# No second writer can reappear
# ---------------------------------------------------------------------------

def _direct_status_assignments() -> list[str]:
    """Every `<expr>.avatar_status = ...` assignment in app/, outside the helper."""
    found: list[str] = []
    for path in APP_DIR.rglob("*.py"):
        if path.name == "avatar_status.py":
            continue  # the one legitimate writer
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in (
                    "avatar_status",
                    "avatar_status_updated_at",
                ):
                    found.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno}")
    return found


def test_avatar_status_has_exactly_one_writer():
    """A guard, not a style rule.

    This is the drift that #41 was: the pair was assigned in three places and
    one of them updated only half of it. Anything that assigns either field
    outside `set_avatar_status` can reintroduce that, so it fails here instead
    of failing silently in production two months later.
    """
    assert _direct_status_assignments() == []


# ---------------------------------------------------------------------------
# The task writes the timestamp on both terminal transitions
# ---------------------------------------------------------------------------

def _user(**kw) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = 1
    user.bio = "A curious fox who loves dense forests."
    user.avatar_status = kw.get("avatar_status", AvatarStatus.pending)
    user.avatar_url = kw.get("avatar_url", None)
    user.avatar_regenerations_this_month = kw.get("regenerations", 1)
    user.avatar_status_updated_at = kw.get("avatar_status_updated_at", None)
    return user


def _claude(payload: dict) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


VALID = {
    "animal": "fox",
    "personality_traits": ["clever"],
    "avatar_description": "A clever fox.",
    "image_prompt": "p",
}


def test_mark_failed_stamps_the_timestamp():
    user = _user()
    _mark_failed(MagicMock(), user)
    assert user.avatar_status == AvatarStatus.failed
    assert user.avatar_status_updated_at is not None


def test_successful_generation_stamps_the_timestamp():
    user = _user(avatar_status_updated_at=datetime.now(UTC) - timedelta(hours=1))
    db = MagicMock()
    db.get.return_value = user

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClaude,
        patch("app.tasks.avatar.generate_avatar_image", return_value="/avatars/x.png"),
    ):
        MockClaude.return_value.messages.create.return_value = _claude(VALID)
        generate_avatar.apply(args=[1])

    assert user.avatar_status == AvatarStatus.ready
    assert datetime.now(UTC) - user.avatar_status_updated_at < timedelta(minutes=1)


def test_task_heartbeats_before_calling_claude():
    """The whole point of #41's concrete failure.

    The timestamp used to record when the task was *enqueued*, so the two-minute
    staleness rule measured broker latency plus work rather than work. Stamping
    at the start of the attempt means a slow generation -- or a retry chain that
    is 60s-spaced by construction -- never looks dead while it is running.
    """
    stale = datetime.now(UTC) - timedelta(hours=1)
    user = _user(avatar_status_updated_at=stale)
    db = MagicMock()
    db.get.return_value = user

    seen: list = []

    def _record_then_fail(*a, **kw):
        seen.append(user.avatar_status_updated_at)
        raise RuntimeError("stop here")

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClaude,
    ):
        MockClaude.return_value.messages.create.side_effect = _record_then_fail
        generate_avatar.apply(args=[1])

    assert seen, "Claude was never called"
    assert seen[0] > stale, "the attempt started without refreshing the heartbeat"


# ---------------------------------------------------------------------------
# End to end: a heartbeat protects the in-flight generation from #40's refund
# ---------------------------------------------------------------------------

@pytest.fixture()
def _stuck_user(db):
    from app.security import hash_password

    user = User(
        email="heartbeat@howl.app",
        password_hash=hash_password("testpass"),
        avatar_status=AvatarStatus.pending,
        bio="A wolf who howls at the moon under the night sky.",
        avatar_regenerations_this_month=1,
        regenerations_reset_at=datetime.now(UTC) - timedelta(days=1),
        avatar_status_updated_at=datetime.now(UTC) - timedelta(minutes=30),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_running_generation_is_not_mistaken_for_a_dead_one(
    client, db, _stuck_user, monkeypatch
):
    """A task enqueued 30 minutes ago but picked up *now* must not look dead.

    Driven through the real task: the regenerate request is issued from inside
    the mocked Claude call, i.e. at the exact moment a real generation is in
    flight. Without the heartbeat the server would agree with the client that
    this generation is dead, refund the slot (#40), accept a second
    regeneration, and then let the first task commit `ready` over the row the
    user just asked to replace -- handing back the avatar they were trying to
    get rid of, at the cost of their only monthly slot.
    """
    from app.security import create_access_token

    headers = {"Cookie": f"access_token={create_access_token(_stuck_user.id)}"}
    # The task owns its own session normally; give it the test's and stop it
    # closing the session the rest of the test still needs.
    monkeypatch.setattr(db, "close", lambda: None)

    in_flight: list[int] = []

    def _regenerate_mid_flight(*a, **kw):
        in_flight.append(client.post("/api/avatar/regenerate", headers=headers).status_code)
        raise RuntimeError("end the task here; the interesting part already happened")

    with (
        patch("app.tasks.avatar.SessionLocal", return_value=db),
        patch("app.tasks.avatar.anthropic.Anthropic") as MockClaude,
    ):
        MockClaude.return_value.messages.create.side_effect = _regenerate_mid_flight
        generate_avatar.apply(args=[_stuck_user.id])

    assert in_flight == [429], "a live generation was mistaken for a dead one"
