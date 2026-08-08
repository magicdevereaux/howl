"""
Shared fixtures for the Howl test suite.

Database strategy
-----------------
Tests use SQLite in-memory so they run without Docker / Postgres.
A session-scoped engine creates the schema once.  Each test gets its
own function-scoped Session; all rows are deleted after the test
completes, giving cheap per-test isolation.

FastAPI dependency overrides
-----------------------------
The ``client`` fixture replaces the ``get_db`` dependency with one that
yields the test session, so every API call in a test uses the same
in-memory database the test itself populates.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models.base import Base
from app.models.user import AvatarStatus, User
from app.security import create_access_token, hash_password

# StaticPool forces all connections to reuse the same underlying DBAPI connection.
# This is essential for SQLite :memory: databases because each *new* connection
# to sqlite:///:memory: gets a completely separate, empty database.  Without
# StaticPool, Base.metadata.create_all() writes to one connection while
# every Session later opens a different connection — meaning "no such table".
TEST_DATABASE_URL = "sqlite:///:memory:"


# ---------------------------------------------------------------------------
# Database engine  (created once per test session)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine():
    eng = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # SQLite disables FK enforcement by default; enable it so ON DELETE CASCADE
    # behaves the same as PostgreSQL in production.
    #
    # Setting isolation_level=None also disables pysqlite's implicit-BEGIN
    # behaviour, which we have to replace by emitting BEGIN ourselves (below).
    # Without this, pysqlite never opens a transaction before DML, so SAVEPOINTs
    # are emitted outside any transaction and effectively autocommit: work done
    # inside a `begin_nested()` block survives a later `rollback()`.  Code that
    # relies on savepoints to recover from an IntegrityError — see
    # `_insert_swipe` / `_get_or_create_match` in app/api/swipes.py — is correct
    # on PostgreSQL but silently untestable without this.  This is SQLAlchemy's
    # documented pysqlite workaround.
    @event.listens_for(eng, "connect")
    def set_sqlite_pragmas(dbapi_conn, _):
        dbapi_conn.isolation_level = None
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(eng, "begin")
    def emit_explicit_begin(conn):
        conn.exec_driver_sql("BEGIN")

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


# ---------------------------------------------------------------------------
# Per-test database session
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(engine):
    """Yield a session and wipe all rows after each test."""
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        # Delete all rows in reverse FK order for isolation
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


# ---------------------------------------------------------------------------
# TestClient wired to the test database
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Common test objects
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_user(db) -> User:
    user = User(
        email="wolf@howl.app",
        password_hash=hash_password("hunter2secure"),
        avatar_status=AvatarStatus.pending,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def auth_headers(test_user: User) -> dict[str, str]:
    """Supply auth via Cookie header (httpOnly cookie-based auth)."""
    token = create_access_token(test_user.id)
    return {"Cookie": f"access_token={token}"}


# ---------------------------------------------------------------------------
# Celery task stubs
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_notify_new_match(monkeypatch):
    """Suppress notify_new_match.delay so match-creating tests don't require Redis."""
    monkeypatch.setattr("app.tasks.notify.notify_new_match.delay", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _open_login_rate_limit(monkeypatch):
    """Keep the auth limiter open by default.

    The limiter counts into a real Redis instance keyed by IP and email. Under
    the test suite every request arrives from the same client IP, so counters
    leak across tests and unrelated login/register assertions start failing with
    429 once a bucket fills up.

    Patched at the source module (`app.services.rate_limit`) rather than at an
    importer, so it intercepts every caller — `enforce_rate_limit` looks the name
    up in its own module at call time. Tests that exercise the limiter itself
    re-patch this in their own body, which takes precedence because it runs after
    this fixture.
    """
    monkeypatch.setattr("app.services.rate_limit.check_rate_limit", lambda *a, **kw: (False, 0))


@pytest.fixture(autouse=True)
def _open_task_locks(monkeypatch):
    """Grant every Celery task lock by default.

    The lock is backed by real Redis and keyed by user id, which repeats across
    tests. Without this, results depend on whether Redis happens to be running
    locally.

    Patched at the client boundary rather than over acquire/release, so tests
    that exercise the lock logic itself can still substitute their own client.
    With no client, acquire fails open and release is a no-op.
    """
    monkeypatch.setattr("app.services.task_lock._get_client", lambda: None)


@pytest.fixture(autouse=True)
def _isolate_chat_rate_limit(monkeypatch):
    """Give each test its own in-memory message-send limiter.

    `app/api/chat.py` used to count sent messages with a DB `COUNT` per request,
    which was hermetic but wasteful; it now uses the shared Redis limiter. Redis
    is real in this suite and its keys are `(user_id, match_id)`, both of which
    repeat across tests, so counters leak between tests *and* between runs — the
    same failure mode as the login limiter above.

    This mirrors the real limiter's semantics exactly (INCR, then block once the
    count exceeds the limit) so a test can still prove the limit fires; it just
    starts from zero every time.
    """
    counters: dict[str, int] = {}

    def fake_check_rate_limit(key: str, limit: int, window: int = 60) -> tuple[bool, int]:
        counters[key] = counters.get(key, 0) + 1
        if counters[key] > limit:
            return True, window
        return False, 0

    monkeypatch.setattr("app.api.chat.check_rate_limit", fake_check_rate_limit)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_pubsub: leave ChatPubSub un-patched (tests that exercise the fan-out itself)",
    )


@pytest.fixture(autouse=True)
def _local_only_chat_pubsub(request, monkeypatch):
    """Keep chat delivery local so tests never touch Redis pub/sub.

    `ChatPubSub` opens a real connection and runs a supervised reader task that
    loops until the process ends. Left live under pytest it keeps each test's
    event loop from closing, which hangs the run outright.

    Neutering publish/subscribe is faithful rather than a cop-out: pub/sub fails
    open to local-only delivery by design (see the module docstring), so this is
    the documented Redis-down path. Cross-replica fan-out is covered separately
    in tests/test_chat_pubsub.py, which drives two replicas against a fake Redis
    and opts out of this fixture with @pytest.mark.real_pubsub.
    """
    if request.node.get_closest_marker("real_pubsub"):
        return

    from app.services.pubsub import ChatPubSub

    async def noop_subscribe(self, match_id: int) -> None:
        return None

    async def noop_unsubscribe(self, match_id: int) -> None:
        return None

    async def noop_publish(self, match_id: int, payload: dict) -> bool:
        return False

    monkeypatch.setattr(ChatPubSub, "subscribe", noop_subscribe)
    monkeypatch.setattr(ChatPubSub, "unsubscribe", noop_unsubscribe)
    monkeypatch.setattr(ChatPubSub, "publish", noop_publish)
