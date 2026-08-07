"""Schema-level invariants (GAPS #20, #22, #23).

These assert things the *database* guarantees, not things the API happens to do.
The distinction matters: every writer in app/ already calls min()/max() before
inserting a Match, but a convention that lives only in application code is one
careless INSERT away from being violated. Raw-SQL inserts and bulk operations
bypass the ORM entirely.

conftest enables PRAGMA foreign_keys=ON, so SQLite enforces FKs and CHECKs the
same way production PostgreSQL does.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.match import Match
from app.models.user import AvatarStatus, User
from app.schemas.user import ProfileUpdate
from app.security import hash_password


def _make_user(db, *, email: str, **kwargs) -> User:
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        avatar_status=AvatarStatus.ready,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# ck_matches_user_order  (#23)
# ---------------------------------------------------------------------------

def test_match_rejects_reversed_user_order(db):
    """(b, a) with b > a must be impossible, so a pair can never match twice.

    uq_match_users only blocks an exact duplicate pair, so without the CHECK the
    same two people could hold both (a, b) and (b, a).
    """
    a = _make_user(db, email="order_a@howl.app")
    b = _make_user(db, email="order_b@howl.app")
    low, high = min(a.id, b.id), max(a.id, b.id)

    db.add(Match(user1_id=high, user2_id=low))   # deliberately reversed
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_match_rejects_self_match(db):
    """user1_id < user2_id is strict, so a user cannot match themselves."""
    a = _make_user(db, email="self_match@howl.app")

    db.add(Match(user1_id=a.id, user2_id=a.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_match_accepts_canonical_order(db):
    """The constraint must not reject the form every writer actually uses."""
    a = _make_user(db, email="canon_a@howl.app")
    b = _make_user(db, email="canon_b@howl.app")

    db.add(Match(user1_id=min(a.id, b.id), user2_id=max(a.id, b.id)))
    db.commit()
    assert db.query(Match).count() == 1


# ---------------------------------------------------------------------------
# age_preference_min <= age_preference_max  (#23)
# ---------------------------------------------------------------------------

def test_inverted_age_preference_is_rejected():
    """40..25 matches nobody and would silently empty the discover queue.

    Per-field validation cannot catch this: both bounds are individually legal.
    """
    with pytest.raises(ValueError, match="age_preference_min"):
        ProfileUpdate(age_preference_min=40, age_preference_max=25)


def test_equal_age_preference_bounds_are_allowed():
    """A single-year window is narrow but meaningful, so it must pass."""
    assert ProfileUpdate(age_preference_min=30, age_preference_max=30).age_preference_min == 30


def test_one_sided_age_preference_still_validates():
    """Sending only one bound is legal — the pair check needs both present."""
    assert ProfileUpdate(age_preference_min=30).age_preference_max is None
    assert ProfileUpdate(age_preference_max=50).age_preference_min is None


def test_inverted_age_preference_is_rejected_through_the_api(client, auth_headers):
    res = client.patch(
        "/api/profile/me",
        headers=auth_headers,
        json={"age_preference_min": 45, "age_preference_max": 20},
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Hot-path indexes  (#20)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("table", "columns"),
    [
        # Reciprocal-like lookup: every match check scanned swipes without it.
        ("swipes", ["target_user_id"]),
        # Queried on message delete / per-sender counts.
        ("messages", ["sender_id"]),
        # SET NULL FK — without an index, every message delete scans reports.
        ("reports", ["message_id"]),
    ],
)
def test_hot_path_column_is_indexed(engine, table, columns):
    indexed = {
        tuple(ix["column_names"][: len(columns)])
        for ix in inspect(engine).get_indexes(table)
    }
    assert tuple(columns) in indexed, (
        f"{table}({', '.join(columns)}) has no index; "
        f"present: {sorted(indexed)}"
    )


def test_messages_have_a_composite_index_for_chat_pagination():
    """Chat pages by match_id ordered on created_at, so it needs both columns.

    Asserted against the model rather than the reflected schema because column
    order within the index is the whole point, and it is what the model declares.
    """
    from app.models.message import Message

    composites = {
        tuple(c.name for c in ix.columns)
        for ix in Message.__table__.indexes
        if len(ix.columns) > 1
    }
    assert ("match_id", "created_at") in composites, f"present: {sorted(composites)}"


# ---------------------------------------------------------------------------
# server_default on creation timestamps  (#22)
# ---------------------------------------------------------------------------

def test_raw_insert_gets_a_created_at_without_the_orm(db):
    """A raw INSERT must not violate NOT NULL on created_at.

    Every timestamp used to be a Python-side default with no server_default, so
    anything bypassing the ORM — raw SQL, a bulk insert, a migration backfill —
    had to supply the value by hand or fail.
    """
    db.execute(
        text(
            "INSERT INTO users (email, password_hash, avatar_status, "
            "email_notifications, is_email_verified, is_bot, profile_needs_regen, "
            "is_premium, avatar_regenerations_this_month, daily_swipes) "
            "VALUES ('raw@howl.app', 'x', 'pending', 1, 0, 0, 0, 0, 0, 0)"
        )
    )
    db.commit()

    created_at = db.execute(
        text("SELECT created_at FROM users WHERE email = 'raw@howl.app'")
    ).scalar()
    assert created_at is not None


def test_creation_timestamps_declare_a_server_default():
    """Each table's creation timestamp carries a server_default.

    Without one, timestamps record the app host's clock rather than the
    database's, so replicas with skewed clocks write inconsistent history.
    """
    from app.models.block import Block
    from app.models.match import Match as MatchModel
    from app.models.message import Message
    from app.models.report import Report
    from app.models.swipe import Swipe
    from app.models.user import User as UserModel

    creation_column = {
        UserModel: "created_at",
        MatchModel: "matched_at",
        Message: "created_at",
        Swipe: "created_at",
        Block: "created_at",
        Report: "created_at",
    }
    missing = [
        f"{model.__tablename__}.{name}"
        for model, name in creation_column.items()
        if model.__table__.c[name].server_default is None
    ]
    assert not missing, f"no server_default on: {missing}"


# ---------------------------------------------------------------------------
# get_db session hygiene  (#23)
# ---------------------------------------------------------------------------

def test_get_db_rolls_back_before_returning_the_session():
    """A failed request must not hand a dirty session back to the pool.

    Without the rollback the connection is returned mid-transaction and the next
    request to pick it up can commit the previous one's half-written state.
    """
    from unittest.mock import MagicMock, patch

    fake = MagicMock()
    with patch("app.db.SessionLocal", return_value=fake):
        from app.db import get_db

        gen = get_db()
        next(gen)
        with pytest.raises(RuntimeError):
            gen.throw(RuntimeError("request blew up"))

    fake.rollback.assert_called_once()
    fake.close.assert_called_once()


def test_get_db_closes_the_session_on_the_happy_path():
    from unittest.mock import MagicMock, patch

    fake = MagicMock()
    with patch("app.db.SessionLocal", return_value=fake):
        from app.db import get_db

        gen = get_db()
        next(gen)
        with pytest.raises(StopIteration):
            next(gen)

    fake.rollback.assert_not_called()
    fake.close.assert_called_once()


# ---------------------------------------------------------------------------
# push_tokens (user_id, token)  (#23)
# ---------------------------------------------------------------------------

def test_shared_device_reassigns_its_push_token(client, db, auth_headers, test_user):
    """A device signing in under a second account must be re-pointed, not rejected.

    GAPS #23 assumed this needed a (user_id, token) pair constraint. It does not:
    the token is deliberately globally unique because one physical device must
    only ever receive notifications for the account currently signed in on it.
    A pair constraint would let two accounts both hold the same device and both
    get its pushes. The correct fix is reassignment, which the API already does
    -- this test pins that behaviour so a future "fix" cannot regress it.
    """
    from app.models.push_token import PushToken
    from app.security import create_access_token

    device = "ExponentPushToken[shared-device]"
    first = _make_user(db, email="device_first@howl.app")

    res = client.post(
        "/api/push-tokens",
        headers={"Cookie": f"access_token={create_access_token(first.id)}"},
        json={"token": device},
    )
    assert res.status_code == 204

    # Same physical device, different account signs in.
    res = client.post("/api/push-tokens", headers=auth_headers, json={"token": device})
    assert res.status_code == 204, "a shared device hand-off must not 409/500"

    rows = db.query(PushToken).filter(PushToken.token == device).all()
    assert len(rows) == 1, "the device must not end up registered twice"
    assert rows[0].user_id == test_user.id, "the token still points at the old account"


def test_match_timestamp_is_timezone_aware_after_reload(db):
    """Documents the naive-datetime gotcha rather than pretending it is fixed.

    Under SQLite a DateTime(timezone=True) column reads back naive, which is why
    app code normalises with replace(tzinfo=utc). See GAPS #22.
    """
    a = _make_user(db, email="tz_a@howl.app")
    b = _make_user(db, email="tz_b@howl.app")
    match = Match(user1_id=min(a.id, b.id), user2_id=max(a.id, b.id))
    db.add(match)
    db.commit()
    db.expire_all()

    reloaded = db.get(Match, match.id)
    assert reloaded.matched_at.tzinfo is None, (
        "SQLite started returning tz-aware datetimes — the replace(tzinfo=utc) "
        "normalisation scattered through app/ can be revisited"
    )
    normalised = reloaded.matched_at.replace(tzinfo=UTC)
    assert (datetime.now(UTC) - normalised).total_seconds() < 60
