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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import scripts.seed_demo_users as seed_mod
from app.models.base import Base
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


def test_seed_second_run_reports_and_removes_prior_rows(seed_db, capsys):
    seed_mod.seed()
    capsys.readouterr()  # discard first run's output

    seed_mod.seed()
    captured = capsys.readouterr()
    assert "Removed 1000 existing demo user(s)." in captured.out


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


def test_seed_delete_filter_also_matches_lookalike_demo_prefixed_emails(seed_db):
    """Documenting real scope, not fixing it: `LIKE 'demo%@howl.app'` matches
    ANY email starting with the literal "demo", not only the `demo{n}@howl.app`
    the script itself generates. A hypothetical real account registered as
    e.g. "demolition@howl.app" would be silently deleted on the next deploy.
    This is a pre-existing behavior of the shipped script; not something this
    test suite should paper over."""
    lookalike = User(
        email="demolition@howl.app",
        password_hash="not-a-real-hash",
        is_bot=False,
    )
    seed_db.add(lookalike)
    seed_db.commit()

    seed_mod.seed()

    assert (
        seed_db.query(User).filter(User.email == "demolition@howl.app").one_or_none()
        is None
    )


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
