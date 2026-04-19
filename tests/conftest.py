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
from sqlalchemy import create_engine
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
    token = create_access_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}
