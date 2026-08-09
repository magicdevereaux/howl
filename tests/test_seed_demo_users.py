"""End-to-end tests for scripts/seed_demo_users.py (GAPS #30).

This script runs on *every production deploy* and was previously only covered
indirectly, via test_bot_response.py's assertions about already-seeded rows.
Nothing actually drove the script itself.

Danger this file exists specifically to avoid: `seed()` calls
`scripts.seed_demo_users.SessionLocal()`, which the script binds at import
time via `from app.db import SessionLocal` — and `app.db.SessionLocal` is
bound to `settings.database_url`, which in this repo's `.env` is the shared
dev Postgres on :5433 that other agents are actively using. SQLAlchemy engines
are lazy (no connection opens at import time — see `app/db.py`), but calling
`seed()` unmodified *would* open one and INSERT 1000 rows into it.

Every test below monkeypatches `scripts.seed_demo_users.SessionLocal` itself
(not `app.db.SessionLocal`) to a sessionmaker bound to a private in-memory
SQLite engine before ever calling `seed()`. That name is resolved at call
time inside `seed()`, so patching the script's own module attribute is
sufficient and never touches Postgres.
"""

import importlib

import bcrypt
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import scripts.seed_demo_users as seed_mod
from app.models.base import Base
from app.models.match import Match
from app.models.message import Message
from app.models.user import AvatarStatus, User

# ---------------------------------------------------------------------------
# Isolated in-memory database, one per test
# ---------------------------------------------------------------------------


@pytest.fixture()
def seed_db(monkeypatch):
    """Point scripts.seed_demo_users.SessionLocal at a private SQLite engine.

    StaticPool is required for the same reason tests/conftest.py uses it: a
    plain sqlite:///:memory: engine hands out a fresh, empty database to every
    new connection, so without it seed()'s own commit()s would each see a
    "table not found" world.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite ignores FK constraints unless asked, exactly as tests/conftest.py
    # does for the main suite. Without this the ON DELETE CASCADE from users ->
    # matches -> messages does not fire, so a test asserting that a reseed
    # preserves conversations would pass even against a destructive seed. The
    # whole point of GAPS-ROUND-2 #39 is that cascade, so it has to be live here.
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):  # pragma: no cover - engine plumbing
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(seed_mod, "SessionLocal", TestSessionLocal)

    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _demo_users(session):
    return (
        session.query(User)
        .filter(User.email.like("demo%@howl.app"))
        .all()
    )


# ---------------------------------------------------------------------------
# Basic seeding
# ---------------------------------------------------------------------------


def test_seed_creates_1000_bot_users(seed_db):
    seed_mod.seed()
    rows = _demo_users(seed_db)
    assert len(rows) == 1000


def test_seed_emails_are_unique_and_follow_the_demo_pattern(seed_db):
    seed_mod.seed()
    emails = [u.email for u in _demo_users(seed_db)]
    assert len(emails) == len(set(emails)) == 1000
    assert all(e.startswith("demo") and e.endswith("@howl.app") for e in emails)


def test_seed_bots_are_flagged_bot_and_email_verified(seed_db):
    seed_mod.seed()
    rows = _demo_users(seed_db)
    assert all(u.is_bot is True for u in rows)
    assert all(u.is_email_verified is True for u in rows)


def test_seed_bots_have_email_notifications_disabled(seed_db):
    """GAPS-ROUND-2 #44: bots' addresses (demo1@howl.app…demo1000@howl.app)
    have no mailbox behind them. email_notifications defaults to True on
    User, so the seed must override it explicitly or wiring an email
    provider immediately hard-bounces the entire bot population."""
    seed_mod.seed()
    rows = _demo_users(seed_db)
    assert rows
    assert all(u.email_notifications is False for u in rows)


def test_seed_avatar_is_ready_with_no_url(seed_db):
    """Bots ship with pre-written avatar data, never a real generated image —
    the whole point is zero Celery/OpenAI dependency for seeding."""
    seed_mod.seed()
    rows = _demo_users(seed_db)
    assert all(u.avatar_status == AvatarStatus.ready for u in rows)
    assert all(u.avatar_url is None for u in rows)
    assert all(u.animal is not None for u in rows)
    assert all(u.avatar_description is not None for u in rows)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_seed_is_idempotent_on_row_count(seed_db):
    seed_mod.seed()
    assert len(_demo_users(seed_db)) == 1000

    seed_mod.seed()  # simulates a second production deploy
    assert len(_demo_users(seed_db)) == 1000


def test_seed_second_run_is_additive_and_says_so(seed_db, capsys):
    """GAPS-ROUND-2 #39: a second deploy must leave existing bots alone."""
    seed_mod.seed()
    capsys.readouterr()  # discard first run's output

    seed_mod.seed()
    captured = capsys.readouterr()
    assert "already present; leaving them" in captured.out
    assert "Seeded 0 new demo user(s)" in captured.out
    assert "Removed" not in captured.out


def test_seed_does_not_touch_non_demo_users(seed_db):
    """The delete filter is `email LIKE 'demo%@howl.app'` — a real account
    with an unrelated email must survive every deploy's reseed untouched."""
    real_user = User(
        email="wolf@howl.app",
        password_hash="not-a-real-hash",
        is_bot=False,
    )
    seed_db.add(real_user)
    seed_db.commit()

    seed_mod.seed()
    seed_mod.seed()  # and a second deploy

    survivor = seed_db.query(User).filter(User.email == "wolf@howl.app").one_or_none()
    assert survivor is not None
    assert len(_demo_users(seed_db)) == 1000


def test_seed_leaves_lookalike_demo_prefixed_emails_alone(seed_db):
    """GAPS-ROUND-2 #39, second half. The old filter was
    `LIKE 'demo%@howl.app'`, which matched ANY address merely *starting* with
    "demo" -- a real `demolition@howl.app` account was deleted on every deploy.
    The script now works from the exact address set it owns."""
    lookalike = User(
        email="demolition@howl.app",
        password_hash="not-a-real-hash",
        is_bot=False,
    )
    seed_db.add(lookalike)
    seed_db.commit()

    seed_mod.seed()
    seed_mod.seed()

    assert (
        seed_db.query(User).filter(User.email == "demolition@howl.app").one_or_none()
        is not None
    )


def test_redeploy_preserves_a_real_users_match_and_chat_history_with_a_bot(seed_db):
    """GAPS-ROUND-2 #39, the harm itself, not a proxy for it.

    `matches.user1_id`/`user2_id` are ON DELETE CASCADE and `messages.match_id`
    cascades from `matches`, so bulk-deleting the bots took every match they were
    in and every message in those matches with them. At a 90% auto-like-back rate
    against a 1000-bot population, that is most of a new user's conversations --
    destroyed by shipping a copy change. The seed_db fixture enables
    PRAGMA foreign_keys=ON, so this test genuinely exercises the cascade.
    """
    seed_mod.seed()

    real = User(email="wolf@howl.app", password_hash="not-a-real-hash", is_bot=False)
    seed_db.add(real)
    seed_db.commit()

    bot = _demo_users(seed_db)[0]
    bot_id_before = bot.id
    low, high = sorted((real.id, bot.id))  # ck_matches_user_order requires user1 < user2
    match = Match(user1_id=low, user2_id=high)
    seed_db.add(match)
    seed_db.commit()

    seed_db.add_all(
        [
            Message(match_id=match.id, sender_id=real.id, content="hey"),
            Message(match_id=match.id, sender_id=bot.id, content="hey yourself"),
        ]
    )
    seed_db.commit()
    match_id = match.id

    seed_mod.seed()  # ship a copy change

    assert seed_db.query(Match).filter(Match.id == match_id).one_or_none() is not None
    assert seed_db.query(Message).filter(Message.match_id == match_id).count() == 2
    # The bot keeps its identity too -- the old path reinserted it under a new id,
    # so even a surviving match would have pointed at a different row.
    assert seed_db.get(User, bot_id_before) is not None


def test_reseed_bots_env_var_restores_the_destructive_path(seed_db, capsys, monkeypatch):
    """The destructive refresh still exists, but only when asked for explicitly.
    A deploy must never set this."""
    seed_mod.seed()
    capsys.readouterr()

    monkeypatch.setenv("RESEED_BOTS", "true")
    seed_mod.seed()
    captured = capsys.readouterr()

    assert "RESEED_BOTS=true: removed 1000 existing demo user(s)" in captured.out
    assert len(_demo_users(seed_db)) == 1000


# ---------------------------------------------------------------------------
# GAPS #4 — random per-deploy password, must never regress to a literal
# ---------------------------------------------------------------------------


def test_demo_password_is_not_the_old_committed_literal():
    """GAPS #4: the bug was bcrypt-ing the literal string
    "howl-demo-placeholder" for every deploy, letting anyone who reads the
    repo log in as any demo user. Pin both ends: the plaintext must not be
    the old literal, and the stored hash must not verify against it either
    (guards against the fix being reverted to some *other* hardcoded value
    that happens to not equal this exact string)."""
    assert seed_mod._DEMO_PASSWORD != "howl-demo-placeholder"
    assert not bcrypt.checkpw(
        b"howl-demo-placeholder", seed_mod._DEMO_PASSWORD_HASH.encode()
    )
    # secrets.token_urlsafe(32) produces a long, high-entropy string --
    # a short hardcoded guess couldn't satisfy this.
    assert len(seed_mod._DEMO_PASSWORD) >= 32
    # And the hash must actually correspond to the plaintext it claims to.
    assert bcrypt.checkpw(
        seed_mod._DEMO_PASSWORD.encode(), seed_mod._DEMO_PASSWORD_HASH.encode()
    )


def test_demo_password_honours_explicit_override_env_var(monkeypatch):
    """DEMO_USER_PASSWORD lets an operator log in as a bot locally. The value
    is computed once at import time, so proving the override branch means
    reloading the module with the env var already set."""
    monkeypatch.setenv("DEMO_USER_PASSWORD", "a-fixed-local-dev-password")
    try:
        importlib.reload(seed_mod)
        assert seed_mod._DEMO_PASSWORD == "a-fixed-local-dev-password"
        assert bcrypt.checkpw(
            b"a-fixed-local-dev-password", seed_mod._DEMO_PASSWORD_HASH.encode()
        )
    finally:
        # Restore a random-password module state so later tests in this file
        # (and any other test importing the same cached module) aren't left
        # pinned to a fixed, predictable password.
        monkeypatch.delenv("DEMO_USER_PASSWORD", raising=False)
        importlib.reload(seed_mod)


# ---------------------------------------------------------------------------
# GAPS #23 — DB-level CHECK constraints must not be violated by generated data
# ---------------------------------------------------------------------------


def test_seed_ages_satisfy_the_age_range_check_constraint(seed_db):
    """`ck_users_age_range` (app/models/user.py) requires
    age IS NULL OR (18 <= age <= 120). If generated data ever violated this,
    seed() would raise IntegrityError and the production deploy would fail
    outright -- so a passing seed() already proves it, but assert the bounds
    directly too as a precise, human-readable regression signal."""
    seed_mod.seed()
    ages = [u.age for u in _demo_users(seed_db) if u.age is not None]
    assert ages, "expected seeded users to have ages set"
    assert all(18 <= age <= 120 for age in ages)


def test_seed_does_not_raise_and_commits_cleanly(seed_db):
    """A failed deploy-time seed must not leave a half-inserted batch. Since
    seed() wraps its work in a single commit, either all 1000 rows land or
    none do; call it twice more to rule out a latent crash on repeat runs."""
    seed_mod.seed()
    seed_mod.seed()
    seed_mod.seed()
    assert len(_demo_users(seed_db)) == 1000


# ---------------------------------------------------------------------------
# Internal consistency of generated data
# ---------------------------------------------------------------------------


def test_seed_age_preference_min_never_exceeds_max(seed_db):
    seed_mod.seed()
    rows = _demo_users(seed_db)
    checked = 0
    for u in rows:
        if u.age_preference_min is not None and u.age_preference_max is not None:
            checked += 1
            assert u.age_preference_min <= u.age_preference_max
    assert checked > 0, "expected at least some rows to have both bounds set"


def test_seed_archetype_distribution_matches_documented_weights(seed_db):
    """The module docstring promises 25/20/20/20/10/5 pct weights across 1000
    users; assert the exact counts the generator is documented to produce."""
    seed_mod.seed()
    rows = _demo_users(seed_db)
    counts: dict[str, int] = {}
    for u in rows:
        counts[u.archetype] = counts.get(u.archetype, 0) + 1

    assert counts == {
        "responsive": 250,
        "slow_burn": 200,
        "flirty": 200,
        "intellectual": 200,
        "ghost": 100,
        "desperate": 50,
    }
