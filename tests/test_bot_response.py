"""Tests for the bot response system."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.match import Match
from app.models.message import Message
from app.models.user import AvatarStatus, User
from app.security import hash_password
from app.tasks.bot_response import (
    ARCHETYPE_MIN_DELAY,
    DESPERATE_FOLLOWUP_SECONDS,
    GHOST_MSG_LIMIT,
    _generate_batch,
    process_bot_responses,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_generate(monkeypatch):
    """Replace Claude call with deterministic stub for all tests in this module."""
    monkeypatch.setattr(
        "app.tasks.bot_response._generate_batch",
        lambda batch: [
            {"match_id": b["match_id"], "bot_id": b["bot_id"], "message": "test reply"}
            for b in batch
        ],
    )


@pytest.fixture()
def patched_session(db, monkeypatch):
    """Wire the task's SessionLocal() to the test SQLite session."""
    monkeypatch.setattr("app.tasks.bot_response.SessionLocal", lambda: db)
    return db


def _make_bot(db, *, email: str, archetype: str = "responsive", **kw) -> User:
    u = User(
        email=email,
        password_hash=hash_password("x"),
        avatar_status=AvatarStatus.ready,
        is_bot=True,
        archetype=archetype,
        name=email.split("@")[0],
        animal="wolf",
        personality_traits=["loyal"],
        **kw,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _make_real(db, *, email: str) -> User:
    u = User(
        email=email,
        password_hash=hash_password("x"),
        avatar_status=AvatarStatus.ready,
        is_bot=False,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _make_match(db, u1: User, u2: User) -> Match:
    m = Match(user1_id=min(u1.id, u2.id), user2_id=max(u1.id, u2.id))
    db.add(m); db.commit(); db.refresh(m)
    return m


def _make_msg(db, *, match_id: int, sender_id: int, content: str = "hi", ago_seconds: int = 0) -> Message:
    created = datetime.now(UTC) - timedelta(seconds=ago_seconds)
    m = Message(match_id=match_id, sender_id=sender_id, content=content, created_at=created)
    db.add(m); db.commit(); db.refresh(m)
    return m


def _bot_msg_count(db, match_id: int, bot_id: int) -> int:
    return db.query(Message).filter(Message.match_id == match_id, Message.sender_id == bot_id).count()


# ---------------------------------------------------------------------------
# Archetype configuration
# ---------------------------------------------------------------------------

def test_archetype_min_delays_defined():
    for a in ("responsive", "slow_burn", "flirty", "intellectual", "ghost", "desperate"):
        assert a in ARCHETYPE_MIN_DELAY
        assert ARCHETYPE_MIN_DELAY[a] >= 0


def test_ghost_limit_and_followup_constants():
    assert GHOST_MSG_LIMIT >= 3
    assert DESPERATE_FOLLOWUP_SECONDS >= 3600   # at least 1 hour


# ---------------------------------------------------------------------------
# Responsive archetype
# ---------------------------------------------------------------------------

def test_responsive_bot_replies_after_min_delay(patched_session):
    db = patched_session
    bot  = _make_bot(db, email="rbot@bot.app", archetype="responsive")
    real = _make_real(db, email="real_r@howl.app")
    m    = _make_match(db, bot, real)
    bot_id, real_id, match_id = bot.id, real.id, m.id   # capture IDs

    _make_msg(db, match_id=match_id, sender_id=real_id, content="Hey!", ago_seconds=400)

    process_bot_responses()

    assert _bot_msg_count(db, match_id, bot_id) == 1


def test_responsive_bot_does_not_reply_too_soon(patched_session):
    db = patched_session
    bot  = _make_bot(db, email="rbot2@bot.app", archetype="responsive")
    real = _make_real(db, email="real_r2@howl.app")
    m    = _make_match(db, bot, real)
    bot_id, real_id, match_id = bot.id, real.id, m.id

    # Message only 60 seconds old — inside the 5-min minimum
    _make_msg(db, match_id=match_id, sender_id=real_id, content="Hey!", ago_seconds=60)

    process_bot_responses()

    assert _bot_msg_count(db, match_id, bot_id) == 0


# ---------------------------------------------------------------------------
# Slow burn archetype
# ---------------------------------------------------------------------------

def test_slow_burn_bot_does_not_reply_too_soon(patched_session):
    db = patched_session
    bot  = _make_bot(db, email="sb@bot.app", archetype="slow_burn")
    real = _make_real(db, email="real_sb@howl.app")
    m    = _make_match(db, bot, real)
    bot_id, real_id, match_id = bot.id, real.id, m.id

    # 30 minutes old, but slow_burn needs 120 min
    _make_msg(db, match_id=match_id, sender_id=real_id, ago_seconds=1800)

    process_bot_responses()

    assert _bot_msg_count(db, match_id, bot_id) == 0


def test_slow_burn_bot_replies_after_120_min(patched_session):
    db = patched_session
    bot  = _make_bot(db, email="sb2@bot.app", archetype="slow_burn")
    real = _make_real(db, email="real_sb2@howl.app")
    m    = _make_match(db, bot, real)
    bot_id, real_id, match_id = bot.id, real.id, m.id

    # 125 minutes old — past the 120-min window
    _make_msg(db, match_id=match_id, sender_id=real_id, ago_seconds=7500)

    process_bot_responses()

    assert _bot_msg_count(db, match_id, bot_id) == 1


# ---------------------------------------------------------------------------
# Ghost archetype
# ---------------------------------------------------------------------------

def test_ghost_replies_below_message_limit(patched_session):
    db = patched_session
    bot  = _make_bot(db, email="ghost@bot.app", archetype="ghost")
    real = _make_real(db, email="real_g@howl.app")
    m    = _make_match(db, bot, real)
    bot_id, real_id, match_id = bot.id, real.id, m.id

    # Bot has sent 2 messages already (below the limit)
    _make_msg(db, match_id=match_id, sender_id=bot_id, content="hey", ago_seconds=600)
    _make_msg(db, match_id=match_id, sender_id=bot_id, content="how are you", ago_seconds=300)
    # Real user replied
    _make_msg(db, match_id=match_id, sender_id=real_id, content="good!", ago_seconds=60)

    process_bot_responses()

    assert _bot_msg_count(db, match_id, bot_id) == 3  # 2 existing + 1 new


def test_ghost_goes_silent_after_limit(patched_session):
    db = patched_session
    bot  = _make_bot(db, email="ghost2@bot.app", archetype="ghost")
    real = _make_real(db, email="real_g2@howl.app")
    m    = _make_match(db, bot, real)
    bot_id, real_id, match_id = bot.id, real.id, m.id

    # Bot already hit the message limit
    for _ in range(GHOST_MSG_LIMIT):
        _make_msg(db, match_id=match_id, sender_id=bot_id, ago_seconds=1000)
    # Real user sends another message
    _make_msg(db, match_id=match_id, sender_id=real_id, content="you there?", ago_seconds=60)

    process_bot_responses()

    # No new messages added — ghost has gone silent
    assert _bot_msg_count(db, match_id, bot_id) == GHOST_MSG_LIMIT


# ---------------------------------------------------------------------------
# Desperate archetype
# ---------------------------------------------------------------------------

def test_desperate_sends_followup_after_2_hours(patched_session):
    db = patched_session
    bot  = _make_bot(db, email="desp@bot.app", archetype="desperate")
    real = _make_real(db, email="real_d@howl.app")
    m    = _make_match(db, bot, real)
    bot_id, real_id, match_id = bot.id, real.id, m.id

    # Bot's last message was 3 hours ago with no reply
    _make_msg(db, match_id=match_id, sender_id=bot_id, ago_seconds=10800)

    process_bot_responses()

    assert _bot_msg_count(db, match_id, bot_id) == 2  # original + follow-up


def test_desperate_does_not_followup_too_soon(patched_session):
    db = patched_session
    bot  = _make_bot(db, email="desp2@bot.app", archetype="desperate")
    real = _make_real(db, email="real_d2@howl.app")
    m    = _make_match(db, bot, real)
    bot_id, real_id, match_id = bot.id, real.id, m.id

    # Only 1 hour ago — below the 2-hour threshold
    _make_msg(db, match_id=match_id, sender_id=bot_id, ago_seconds=3600)

    process_bot_responses()

    assert _bot_msg_count(db, match_id, bot_id) == 1  # no follow-up yet


def test_desperate_no_followup_when_real_user_replied(patched_session):
    db = patched_session
    bot  = _make_bot(db, email="desp3@bot.app", archetype="desperate")
    real = _make_real(db, email="real_d3@howl.app")
    m    = _make_match(db, bot, real)
    bot_id, real_id, match_id = bot.id, real.id, m.id

    _make_msg(db, match_id=match_id, sender_id=bot_id, ago_seconds=10800)
    # Real user replied after bot's message — last_msg.sender_id is now real_id
    _make_msg(db, match_id=match_id, sender_id=real_id, content="sorry!", ago_seconds=60)

    process_bot_responses()

    # Task should generate a normal reply (not a follow-up), so count goes from 1 → 2
    assert _bot_msg_count(db, match_id, bot_id) == 2


# ---------------------------------------------------------------------------
# Isolation: bots don't reply to other bots
# ---------------------------------------------------------------------------

def test_bots_do_not_reply_to_other_bots(patched_session):
    db = patched_session
    bot1 = _make_bot(db, email="b1@bot.app", archetype="responsive")
    bot2 = _make_bot(db, email="b2@bot.app", archetype="responsive")
    m    = _make_match(db, bot1, bot2)
    bot1_id, bot2_id, match_id = bot1.id, bot2.id, m.id

    _make_msg(db, match_id=match_id, sender_id=bot2_id, ago_seconds=600)

    process_bot_responses()

    assert _bot_msg_count(db, match_id, bot1_id) == 0


# ---------------------------------------------------------------------------
# _generate_batch unit tests (Claude parsing)
# ---------------------------------------------------------------------------

def test_generate_batch_falls_back_on_invalid_json(monkeypatch):
    import anthropic as ant_module

    class _Msg:
        text = "not valid json"

    class _Resp:
        content = [_Msg()]

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                return _Resp()

    monkeypatch.setattr(ant_module, "Anthropic", lambda **kw: _Client())

    batch = [{"match_id": 1, "bot_id": 9, "name": "X", "animal": "wolf",
               "traits": [], "archetype": "responsive",
               "response_type": "reply", "message_received": "hi", "history": []}]
    assert _generate_batch(batch) == []


def test_generate_batch_parses_valid_json(monkeypatch):
    import json

    import anthropic as ant_module

    payload = json.dumps([{"index": 0, "message": "Hey there!"}])

    class _Msg:
        text = payload

    class _Resp:
        content = [_Msg()]

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                return _Resp()

    monkeypatch.setattr(ant_module, "Anthropic", lambda **kw: _Client())

    batch = [{"match_id": 5, "bot_id": 7, "name": "Luna", "animal": "fox",
               "traits": ["clever"], "archetype": "flirty",
               "response_type": "reply", "message_received": "How are you?", "history": []}]
    result = _generate_batch(batch)
    assert len(result) == 1
    assert result[0] == {"match_id": 5, "bot_id": 7, "message": "Hey there!"}


# ---------------------------------------------------------------------------
# Seed script validation
# ---------------------------------------------------------------------------

def test_seed_produces_1000_users():
    from scripts.seed_demo_users import DEMO_USERS
    assert len(DEMO_USERS) == 1000


def test_seed_archetype_distribution():
    from scripts.seed_demo_users import DEMO_USERS
    counts: dict[str, int] = {}
    for u in DEMO_USERS:
        counts[u["archetype"]] = counts.get(u["archetype"], 0) + 1

    assert counts.get("desperate", 0) <= 70          # rare — ~5%
    assert counts.get("responsive", 0) >= 200         # most common
    assert set(counts.keys()) == {
        "responsive", "slow_burn", "flirty", "intellectual", "ghost", "desperate"
    }


def test_seed_desperate_bios_feel_needy():
    from scripts.seed_demo_users import _BIOS
    # Every desperate bio should contain at least one emotionally loaded word
    needy_words = {
        "half", "soulmate", "hurt", "alone", "chance", "real", "ready",
        "prove", "loyal", "waste", "tired", "love", "right", "regret", "too much",
    }
    for bio in _BIOS["desperate"]:
        bio_lower = bio.lower()
        assert any(w in bio_lower for w in needy_words), f"Bio not needy enough: {bio}"


def test_seed_all_users_have_required_fields():
    from scripts.seed_demo_users import DEMO_USERS
    for u in DEMO_USERS:
        assert u["email"].endswith("@howl.app")
        assert u["archetype"] in {"responsive", "slow_burn", "flirty", "intellectual", "ghost", "desperate"}
        assert u["animal"]
        assert u["bio"]
