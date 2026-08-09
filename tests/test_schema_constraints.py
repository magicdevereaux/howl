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
from sqlalchemy import DateTime, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.match import Match
from app.models.types import UtcDateTime
from app.models.user import AvatarStatus, User
from app.schemas.user import ProfileUpdate
from app.security import hash_password


def _make_user(db, *, email: str, **kwargs) -> User:
    """Build a *legal* ready user.

    `animal` is defaulted rather than left NULL because
    ck_users_ready_avatar_has_animal makes ready-with-no-animal impossible — and
    it is impossible in production too, so a fixture that produced it was
    building a user the app can never create. Pass animal=None explicitly to
    construct the illegal state on purpose.
    """
    kwargs.setdefault("animal", "wolf")
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


# ---------------------------------------------------------------------------
# ck_users_ready_avatar_has_animal  (#23)
# ---------------------------------------------------------------------------
#
# "avatar_status='ready' implies animal IS NOT NULL". GAPS #23 deferred this
# pending a transactional ready-transition; every writer turned out to already
# flip status in the same commit that writes animal, so the invariant held and
# the constraint just moves enforcement into the database.
#
# The constraint is deliberately about `animal` and NOT `avatar_url` — see
# test_bot_shape_is_permitted for the two states that make a url-based version
# outright false.

def test_ready_status_without_an_animal_is_rejected(db):
    """The state the constraint exists to forbid.

    A ready row is admitted to the discover queue on avatar_status alone
    (app/api/users.py), and the spirit animal *is* the product. Both clients
    fall back to a generic emoji instead of erroring, so this would sit in a
    thousand queues silently.
    """
    with pytest.raises(IntegrityError):
        _make_user(db, email="ready_no_animal@howl.app", animal=None)
    db.rollback()


def test_clearing_the_animal_on_a_ready_row_is_rejected(db):
    """The UPDATE form, not just the INSERT form."""
    user = _make_user(db, email="clear_animal@howl.app", animal="otter")

    user.animal = None
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_bot_shape_is_permitted(db):
    """ready + animal + avatar_url IS NULL must be legal.

    This is the 1000-bot seed shape (scripts/seed_demo_users.py): bots never get
    a DALL-E image and render from `animal` alone. It is also the emoji-fallback
    shape for real users, since generate_avatar treats image generation as
    best-effort. Constraining avatar_url instead of animal would have been the
    intuitive choice and would have aborted every production deploy's seed step.
    """
    bot = _make_user(
        db,
        email="bot_shape@howl.app",
        animal="wolf",
        avatar_url=None,
        is_bot=True,
    )
    assert bot.avatar_status is AvatarStatus.ready
    assert bot.avatar_url is None


@pytest.mark.parametrize("status", [AvatarStatus.pending, AvatarStatus.failed])
def test_non_ready_status_may_have_no_animal(db, status):
    """pending is a fresh signup; failed is generation that never produced one.

    Neither is renderable, neither is in the discover queue, and both legitimately
    have animal IS NULL — the constraint must not reach them.
    """
    user = User(
        email=f"{status.value}_no_animal@howl.app",
        password_hash=hash_password("testpass1"),
        avatar_status=status,
        animal=None,
    )
    db.add(user)
    db.commit()
    assert db.get(User, user.id).animal is None


def test_the_generate_avatar_ready_transition_does_not_trip_the_constraint(db):
    """The pipeline's own write, in the order app/tasks/avatar.py performs it.

    A CHECK is evaluated per *statement*, so what matters is that the status flip
    and the animal write land in one flush. This mirrors that block exactly; if
    someone splits it with a commit or flush, this fails.
    """
    user = User(
        email="pipeline@howl.app",
        password_hash=hash_password("testpass1"),
        avatar_status=AvatarStatus.pending,
        bio="I hike alone and like the cold.",
    )
    db.add(user)
    db.commit()

    # Exactly the assignment block from generate_avatar, single commit.
    user.animal = "wolf"
    user.personality_traits = ["loyal", "watchful"]
    user.avatar_description = "A grey wolf under aurora light."
    user.avatar_url = None            # DALL-E unconfigured — emoji fallback
    user.avatar_status = AvatarStatus.ready
    db.commit()

    assert db.get(User, user.id).avatar_status is AvatarStatus.ready


def test_the_regeneration_transition_does_not_trip_the_constraint(db):
    """ready+animal -> pending+NULL, the way regenerate/profile-update write it.

    The reverse direction is the one with a trap: clearing animal while status is
    still 'ready' violates the constraint, so the two writes must flush together.
    They do — both call sites assign every field then commit once.
    """
    user = _make_user(db, email="regen@howl.app", animal="fox", avatar_url="/avatars/f.png")

    user.animal = None
    user.personality_traits = None
    user.avatar_description = None
    user.avatar_url = None
    user.avatar_status = AvatarStatus.pending
    db.commit()

    reloaded = db.get(User, user.id)
    assert reloaded.avatar_status is AvatarStatus.pending
    assert reloaded.animal is None


def test_regeneration_limit_flush_happens_before_the_avatar_is_cleared(db):
    """Pins the ordering that keeps app/api/avatar.py safe under the constraint.

    _enforce_regen_limit calls db.flush() when the 30-day window has expired. That
    flush is only safe because it runs *before* any avatar field is touched, so it
    writes a row still in its previous consistent state. Moving it after the
    clearing block would flush ready+animal=NULL and raise IntegrityError.
    """
    user = _make_user(db, email="regen_flush@howl.app", animal="hawk")

    # The limit check's own write: counter + window only, avatar untouched.
    user.avatar_regenerations_this_month = 0
    user.regenerations_reset_at = datetime.now(UTC)
    db.flush()          # must not raise — row is still ready *with* an animal

    # Only now does the caller clear the avatar, and commits it as one unit.
    user.animal = None
    user.avatar_status = AvatarStatus.pending
    db.commit()

    assert db.get(User, user.id).avatar_status is AvatarStatus.pending


def test_the_seed_script_user_shape_satisfies_the_constraint():
    """Every seeded bot must be insertable, without importing 375 lines of script.

    scripts/seed_demo_users.py runs on every production deploy. Asserting against
    its actual DEMO_USERS data means a future archetype that forgets `animal`
    fails here rather than at deploy time.
    """
    from scripts.seed_demo_users import DEMO_USERS

    animal_less = [u["email"] for u in DEMO_USERS if not u.get("animal")]
    assert not animal_less, (
        f"{len(animal_less)} seeded bots have no animal but are seeded as "
        f"avatar_status=ready: {animal_less[:5]}"
    )


# ---------------------------------------------------------------------------
# UtcDateTime  (#22)
# ---------------------------------------------------------------------------
#
# Every timestamp column is app.models.types.UtcDateTime, a TypeDecorator over
# DateTime(timezone=True) that coerces naive values to UTC-aware on the way out
# of the database. These tests pin the guarantee the rest of app/ now relies on:
# a stored timestamp can be compared against datetime.now(UTC) directly, with no
# replace(tzinfo=utc) at the call site.
#
# The DDL is unchanged -- a TypeDecorator is Python-side only -- so there is no
# migration for this. `alembic revision --autogenerate` against a throwaway
# PostgreSQL database at head emits an empty migration, which is what
# test_no_timestamp_column_changed_its_ddl asserts more cheaply.

def test_match_timestamp_is_timezone_aware_after_reload(db):
    """The ORM round-trip yields an aware datetime, not a naive one.

    This test used to assert the *opposite* -- it documented SQLite returning
    naive datetimes as a known gotcha. UtcDateTime removes the gotcha, so the
    assertion is inverted rather than deleted: if this ever goes back to naive,
    every comparison against datetime.now(UTC) in app/ starts raising TypeError.
    """
    a = _make_user(db, email="tz_a@howl.app")
    b = _make_user(db, email="tz_b@howl.app")
    match = Match(user1_id=min(a.id, b.id), user2_id=max(a.id, b.id))
    db.add(match)
    db.commit()
    db.expire_all()

    reloaded = db.get(Match, match.id)
    assert reloaded.matched_at.tzinfo is not None, (
        "matched_at came back naive — UtcDateTime is not applied, or was "
        "replaced with a bare DateTime(timezone=True)"
    )
    # No replace(tzinfo=utc) needed: this is the whole point of the type.
    assert (datetime.now(UTC) - reloaded.matched_at).total_seconds() < 60


def test_every_model_timestamp_column_uses_utcdatetime():
    """A mechanism applied to some columns teaches the wrong lesson.

    GAPS #22's complaint was not that four specific columns lacked normalisation
    -- it was that normalisation was a thing you had to remember. Half-applying
    the type reintroduces exactly that, so this asserts *all* of them.
    """
    from app.models.base import Base

    wrong = [
        f"{table.name}.{col.name}"
        for table in Base.metadata.sorted_tables
        for col in table.columns
        if isinstance(col.type, DateTime) and not isinstance(col.type, UtcDateTime)
    ]
    assert not wrong, f"timestamp columns not using UtcDateTime: {wrong}"


def test_no_timestamp_column_changed_its_ddl():
    """UtcDateTime must compile to exactly what the migrations already created.

    This is what makes "no Alembic migration needed" true rather than hopeful.
    If impl or load_dialect_impl ever drifts, the models silently stop matching
    the deployed schema and autogenerate starts proposing ALTERs.
    """
    from sqlalchemy.dialects import postgresql, sqlite

    for dialect in (postgresql.dialect(), sqlite.dialect()):
        assert UtcDateTime().compile(dialect=dialect) == (
            DateTime(timezone=True).compile(dialect=dialect)
        ), f"UtcDateTime DDL diverged from DateTime(timezone=True) on {dialect.name}"


# A naive wall-clock literal, written the way a raw SQL statement, an Alembic
# backfill or a non-ORM writer would write it. Under SQLite this is what
# actually sits in the column for *every* timestamp.
_NAIVE_LITERAL = "2026-01-15 08:30:00"
_EXPECTED = datetime(2026, 1, 15, 8, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "column",
    [
        # The two users columns GAPS #22 named as still lacking normalisation.
        "regenerations_reset_at",
        "avatar_status_updated_at",
        # These two had it, via #14 and #18 — assert the type subsumes them.
        "swipes_reset_at",
        "email_verification_token_expires_at",
    ],
)
def test_naive_user_timestamp_written_by_raw_sql_reads_back_aware(db, column):
    """A value that bypassed the ORM entirely still loads as UTC-aware.

    Bypassing the ORM is the case that matters: app.api.avatar._enforce_regen_limit
    compares regenerations_reset_at against datetime.now(UTC), and nothing
    guarantees the row was written by the ORM. A migration backfill, a raw
    UPDATE, or SQLite's own text storage all produce a naive value.
    """
    user = _make_user(db, email=f"naive_{column}@howl.app")

    db.execute(
        text(f"UPDATE users SET {column} = :value WHERE id = :id"),  # noqa: S608
        {"value": _NAIVE_LITERAL, "id": user.id},
    )
    db.commit()
    db.expire_all()

    value = getattr(db.get(User, user.id), column)
    assert value.tzinfo is not None, f"{column} came back naive"
    assert value == _EXPECTED
    # The payoff: arithmetic against an aware "now" without normalising first.
    assert (datetime.now(UTC) - value).total_seconds() > 0


@pytest.mark.parametrize("column", ["read_at", "deleted_at"])
def test_naive_message_timestamp_written_by_raw_sql_reads_back_aware(db, column):
    """messages.read_at / deleted_at — the other two columns GAPS #22 named.

    Both are nullable and both are compared against an aware now() when marking
    a conversation read and when filtering soft-deleted messages.
    """
    from app.models.message import Message

    a = _make_user(db, email=f"msg_{column}_a@howl.app")
    b = _make_user(db, email=f"msg_{column}_b@howl.app")
    match = Match(user1_id=min(a.id, b.id), user2_id=max(a.id, b.id))
    db.add(match)
    db.commit()

    message = Message(match_id=match.id, sender_id=a.id, content="howl")
    db.add(message)
    db.commit()

    assert getattr(message, column) is None, "NULL must survive as None, not 1970"

    db.execute(
        text(f"UPDATE messages SET {column} = :value WHERE id = :id"),  # noqa: S608
        {"value": _NAIVE_LITERAL, "id": message.id},
    )
    db.commit()
    db.expire_all()

    value = getattr(db.get(Message, message.id), column)
    assert value.tzinfo is not None, f"messages.{column} came back naive"
    assert value == _EXPECTED


def test_updated_at_onupdate_fires_for_the_bulk_update_forms_the_app_uses(db):
    """Refutes GAPS #22's claim that bulk .update() skips updated_at's onupdate.

    #22 records this as "unchanged and still a real trap", naming app/api/swipes.py
    and app/tasks/notify.py. Measured, it is not a trap: SQLAlchemy's UPDATE
    compiler adds updated_at to the SET clause for Core update(), ORM
    Query.update() *and* bulk_update_mappings. The only form that skips a
    Python-side onupdate is a raw text() UPDATE, which bypasses the compiler
    entirely — and app/ contains no raw SQL writes at all.

    (notify.py no longer bulk-updates anything either; its bulk statement is a
    .delete(), where onupdate is meaningless.)

    Pinned as a test so nobody "fixes" a non-problem by adding a trigger, and so
    that introducing a raw-SQL UPDATE of users has to argue with this first.

    Compared against a fixed sentinel rather than "the previous value", because
    two statements can land inside one clock tick on Windows and produce byte-
    identical timestamps — which made the >-based version of this test flaky.
    """
    from sqlalchemy import update

    user = _make_user(db, email="onupdate@howl.app")
    stale = datetime(2020, 1, 1, tzinfo=UTC)

    def park_updated_at() -> None:
        """Force updated_at to a value now() can never collide with."""
        db.execute(
            update(User).where(User.id == user.id).values(updated_at=stale),
            execution_options={"synchronize_session": False},
        )
        db.commit()
        assert db.get(User, user.id).updated_at == stale

    # The exact shape of app/api/swipes.py's _consume_swipe_quota: a Core
    # update() with updated_at absent from values().
    park_updated_at()
    db.execute(
        update(User).where(User.id == user.id).values(daily_swipes=5),
        execution_options={"synchronize_session": False},
    )
    db.commit()
    assert db.get(User, user.id).updated_at != stale, (
        "Core update() left updated_at at the sentinel — onupdate did not fire"
    )

    park_updated_at()
    db.query(User).filter(User.id == user.id).update(
        {"daily_swipes": 6}, synchronize_session=False
    )
    db.commit()
    assert db.get(User, user.id).updated_at != stale, (
        "Query.update() left updated_at at the sentinel — onupdate did not fire"
    )


def test_an_explicit_updated_at_wins_over_the_onupdate(db):
    """A caller that sets updated_at itself must not have it overwritten.

    app/tasks/avatar.py assigns updated_at by hand alongside the status flip. If
    onupdate clobbered that, the value written would not be the value intended.
    """
    from sqlalchemy import update

    user = _make_user(db, email="explicit_updated_at@howl.app")
    sentinel = datetime(2020, 1, 1, tzinfo=UTC)

    db.execute(
        update(User).where(User.id == user.id).values(daily_swipes=1, updated_at=sentinel),
        execution_options={"synchronize_session": False},
    )
    db.commit()

    assert db.get(User, user.id).updated_at == sentinel


def test_null_timestamp_stays_none():
    """NULL must not be coerced into an epoch — it is a meaningful state here.

    read_at NULL means unread; regenerations_reset_at NULL means "no window has
    opened yet". A type that turned those into 1970-01-01 would break both.
    """
    coerce = UtcDateTime()
    assert coerce.process_result_value(None, None) is None
    assert coerce.process_bind_param(None, None) is None


def test_naive_inbound_value_is_assumed_utc_not_rejected():
    """The documented inbound policy: naive means UTC.

    Chosen over raising because a row already stored cannot be un-stored by
    refusing to load it, and because every writer in this codebase already uses
    datetime.now(UTC) — the convention is settled, so encoding it is honest.
    """
    naive = datetime(2026, 1, 15, 8, 30)
    assert UtcDateTime().process_bind_param(naive, None) == _EXPECTED


def test_aware_non_utc_value_is_converted_not_stripped():
    """An offset must be honoured, never discarded.

    Stripping tzinfo from 08:30+02:00 would store 08:30 UTC and move the instant
    two hours. Converting stores 06:30 UTC, which is the same moment.
    """
    from datetime import timedelta, timezone

    plus_two = datetime(2026, 1, 15, 10, 30, tzinfo=timezone(timedelta(hours=2)))
    converted = UtcDateTime().process_bind_param(plus_two, None)

    assert converted == _EXPECTED, "the instant moved — offset was stripped, not converted"
    assert converted.tzinfo is UTC
