"""Concurrency tests for POST /api/swipes and DELETE /api/swipes/last (GAPS #14).

The suite runs on a single in-memory SQLite connection, so real threads cannot
produce a real interleaving. Instead each test injects the *effect* of a
concurrent request at the exact instant the old code was vulnerable — between a
check and the write that depended on it — by patching the mapped class's
``__init__``, which is the only statement the old code executed between its
in-Python check and its flush.

The injected row/counter change is committed, so it is durable state from
"another transaction" as far as the request under test is concerned. Every test
here fails against the pre-fix handler:

  - duplicate swipe   -> unhandled IntegrityError (500)
  - quota             -> 200, and daily_swipes ends up above the limit
  - duplicate match   -> unhandled IntegrityError (500)
  - undo ordering     -> undoes the wrong swipe
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, update

from app.api.swipes import _DAILY_SWIPE_LIMIT
from app.models.match import Match
from app.models.swipe import Swipe, SwipeDirection
from app.models.user import AvatarStatus, User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, *, email: str, **kwargs) -> User:
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        avatar_status=AvatarStatus.ready,
        **{"animal": "wolf", **kwargs},
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _headers(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token(user.id)}"}


def _swipe(client, user, target_id, direction="like"):
    return client.post(
        "/api/swipes",
        headers=_headers(user),
        json={"target_user_id": target_id, "direction": direction},
    )


def _once(monkeypatch, cls, side_effect):
    """Run ``side_effect(**kwargs)`` the first time ``cls`` is constructed.

    ``cls.__init__`` is patched on the real mapped class rather than a subclass,
    so ``db.query(cls)`` and ``cls.column`` keep working inside the handler.
    """
    original = cls.__init__
    fired: list[int] = []

    def racing_init(self, **kwargs):
        if not fired:
            fired.append(1)
            side_effect(**kwargs)
        original(self, **kwargs)

    monkeypatch.setattr(cls, "__init__", racing_init)
    return fired


# ---------------------------------------------------------------------------
# Duplicate swipe: check-then-insert
# ---------------------------------------------------------------------------

def test_concurrent_duplicate_swipe_returns_409(client, db, monkeypatch, test_user):
    """A swipe committed by another request after our check must give 409, not 500.

    Old code SELECTed for an existing swipe, found none, then flushed its own
    insert straight into `uq_swipe_user_target` -> unhandled IntegrityError.
    """
    other = _make_user(db, email="race_dup@howl.app", animal="fox")

    def concurrent_insert(**kwargs):
        db.execute(
            insert(Swipe.__table__).values(
                user_id=kwargs["user_id"],
                target_user_id=kwargs["target_user_id"],
                direction=SwipeDirection.like,
                created_at=datetime.now(UTC),
            )
        )
        db.commit()

    fired = _once(monkeypatch, Swipe, concurrent_insert)

    res = _swipe(client, test_user, other.id)

    assert fired, "the interleaving was never injected — test seam is wrong"
    assert res.status_code == 409
    assert res.json()["detail"] == "Already swiped on this user."
    # Exactly one swipe row survives: the concurrent one.
    assert db.query(Swipe).filter(
        Swipe.user_id == test_user.id, Swipe.target_user_id == other.id
    ).count() == 1


def test_concurrent_duplicate_swipe_does_not_charge_quota(client, db, monkeypatch, test_user):
    """Losing the dedup race must not consume a swipe from the daily quota."""
    other = _make_user(db, email="race_dup_quota@howl.app")
    test_user.daily_swipes = 5
    test_user.swipes_reset_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()

    def concurrent_insert(**kwargs):
        db.execute(
            insert(Swipe.__table__).values(
                user_id=kwargs["user_id"],
                target_user_id=kwargs["target_user_id"],
                direction=SwipeDirection.like,
                created_at=datetime.now(UTC),
            )
        )
        db.commit()

    _once(monkeypatch, Swipe, concurrent_insert)

    assert _swipe(client, test_user, other.id).status_code == 409

    db.refresh(test_user)
    assert test_user.daily_swipes == 5


# ---------------------------------------------------------------------------
# Daily quota: check-then-increment
# ---------------------------------------------------------------------------

def test_concurrent_swipes_cannot_exceed_daily_limit(client, db, monkeypatch, test_user):
    """The quota is a hard ceiling even when two requests pass the check together.

    Old code read `daily_swipes` (19 < 20 -> allowed), then did `+= 1` on a
    value another request had already pushed to the limit, ending at 21.
    """
    other = _make_user(db, email="race_quota@howl.app")
    test_user.daily_swipes = _DAILY_SWIPE_LIMIT - 1
    test_user.swipes_reset_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()

    def concurrent_last_swipe(**kwargs):
        # Another request claims the final slot and commits.
        db.execute(
            update(User.__table__)
            .where(User.__table__.c.id == test_user.id)
            .values(daily_swipes=_DAILY_SWIPE_LIMIT)
        )
        db.commit()

    fired = _once(monkeypatch, Swipe, concurrent_last_swipe)

    res = _swipe(client, test_user, other.id)

    assert fired, "the interleaving was never injected — test seam is wrong"
    assert res.status_code == 429
    assert res.json()["detail"]["code"] == "daily_limit_reached"

    db.refresh(test_user)
    assert test_user.daily_swipes == _DAILY_SWIPE_LIMIT, "quota ceiling was breached"
    # The rejected swipe left no row behind.
    assert db.query(Swipe).filter(Swipe.user_id == test_user.id).count() == 0


def test_quota_window_rollover_still_wins_the_race(client, db, monkeypatch, test_user):
    """A concurrent request that maxes the counter must not block a rolled-over window.

    The reset and the increment happen in one statement, so an expired window
    is honoured regardless of what the counter says.
    """
    other = _make_user(db, email="race_rollover@howl.app")
    test_user.daily_swipes = _DAILY_SWIPE_LIMIT - 1
    test_user.swipes_reset_at = datetime.now(UTC) - timedelta(hours=25)
    db.commit()

    def concurrent_last_swipe(**kwargs):
        db.execute(
            update(User.__table__)
            .where(User.__table__.c.id == test_user.id)
            .values(daily_swipes=_DAILY_SWIPE_LIMIT)
        )
        db.commit()

    _once(monkeypatch, Swipe, concurrent_last_swipe)

    assert _swipe(client, test_user, other.id).status_code == 200

    db.refresh(test_user)
    assert test_user.daily_swipes == 1  # window reset, then this swipe counted


# ---------------------------------------------------------------------------
# Duplicate Match rows on simultaneous mutual likes
# ---------------------------------------------------------------------------

def test_simultaneous_mutual_like_creates_one_match(client, db, monkeypatch, test_user):
    """Both halves of a mutual like landing at once must yield exactly one Match.

    Old code checked for the reciprocal like then inserted a Match with no
    conflict handling, so the second insert hit `uq_match_users` -> 500.
    """
    other = _make_user(db, email="race_match@howl.app", name="Iris", animal="owl")
    db.add(Swipe(user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like))
    db.commit()

    notified: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.api.swipes.notify_new_match.delay",
        lambda match_id, user_id: notified.append((match_id, user_id)),
    )

    created: list[int] = []

    def concurrent_match(**kwargs):
        # The other user's request wins the insert and commits first.
        result = db.execute(
            insert(Match.__table__).values(
                user1_id=kwargs["user1_id"],
                user2_id=kwargs["user2_id"],
                matched_at=datetime.now(UTC),
            )
        )
        db.commit()
        created.append(result.inserted_primary_key[0])

    fired = _once(monkeypatch, Match, concurrent_match)

    res = _swipe(client, test_user, other.id)

    assert fired, "the interleaving was never injected — test seam is wrong"
    assert res.status_code == 200
    body = res.json()
    assert body["matched"] is True
    # We adopted the winner's row rather than writing a second one.
    assert db.query(Match).count() == 1
    assert body["match"]["id"] == created[0]
    assert body["match"]["other_user"]["name"] == "Iris"
    # The creator notifies; the loser must not send a duplicate push.
    assert notified == []


def test_uncontended_mutual_like_still_notifies(client, db, monkeypatch, test_user):
    """Guard against the fix suppressing the normal new-match notification."""
    other = _make_user(db, email="solo_match@howl.app", animal="hawk")
    db.add(Swipe(user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like))
    db.commit()

    notified: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "app.api.swipes.notify_new_match.delay",
        lambda match_id, user_id: notified.append((match_id, user_id)),
    )

    assert _swipe(client, test_user, other.id).status_code == 200
    match = db.query(Match).one()
    assert notified == [(match.id, other.id)]


# ---------------------------------------------------------------------------
# undo_last_swipe ordering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "second_offset",
    [
        timedelta(0),             # identical timestamps — SQLite tie, arbitrary order
        timedelta(seconds=-2),    # clock skew across replicas: newer row, older stamp
    ],
    ids=["tied_timestamps", "skewed_clock"],
)
def test_undo_uses_insertion_order_not_created_at(client, db, test_user, second_offset):
    """"Last swipe" means the highest id, not the largest created_at.

    `created_at` is a Python-side default with no `server_default`, so two
    swipes can carry the same stamp, and two app replicas with skewed clocks can
    write them out of order. Ordering by `created_at` then undoes the wrong
    swipe, which restores the wrong card to the discover stack.
    """
    first = _make_user(db, email="undo_first@howl.app", name="First")
    second = _make_user(db, email="undo_second@howl.app", name="Second")

    stamp = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    db.add(Swipe(
        user_id=test_user.id, target_user_id=first.id,
        direction=SwipeDirection.pass_, created_at=stamp,
    ))
    db.commit()
    db.add(Swipe(
        user_id=test_user.id, target_user_id=second.id,
        direction=SwipeDirection.pass_, created_at=stamp + second_offset,
    ))
    db.commit()

    res = client.delete("/api/swipes/last", headers=_headers(test_user))
    assert res.status_code == 200
    assert res.json()["target_user_id"] == second.id
    assert res.json()["user"]["name"] == "Second"

    remaining = db.query(Swipe).filter(Swipe.user_id == test_user.id).all()
    assert [s.target_user_id for s in remaining] == [first.id]


def test_concurrent_undo_second_caller_gets_404(client, db, monkeypatch, test_user):
    """Two undos racing on the same swipe: one wins, the other 404s cleanly.

    Injected at `db.query(User)` — the target lookup, which sits between the
    handler's "find my last swipe" SELECT and its DELETE. (`get_current_user`
    uses `db.get`, so this is the first `db.query(User)` of the request.)

    Without the rowcount guard the loser's ORM `db.delete()` raises
    StaleDataError (500), and it still goes on to delete the match and the other
    party's swipe — undoing state the winner's request never touched.
    """
    other = _make_user(db, email="race_undo@howl.app")
    swipe = Swipe(user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.like)
    db.add(swipe)
    db.add(Swipe(user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like))
    db.commit()
    swipe_id = swipe.id
    db.add(Match(user1_id=min(test_user.id, other.id), user2_id=max(test_user.id, other.id)))
    db.commit()

    real_query = type(db).query
    fired: list[int] = []

    def racing_query(self, *entities, **kw):
        if not fired and entities and entities[0] is User:
            fired.append(1)
            # The other undo request deletes the same swipe and commits.
            self.execute(Swipe.__table__.delete().where(Swipe.__table__.c.id == swipe_id))
            self.commit()
        return real_query(self, *entities, **kw)

    monkeypatch.setattr(type(db), "query", racing_query)
    res = client.delete("/api/swipes/last", headers=_headers(test_user))
    monkeypatch.undo()

    assert fired, "the interleaving was never injected — test seam is wrong"
    assert res.status_code == 404
    # The loser must not have cascaded into the match or the other party's swipe.
    assert db.query(Match).count() == 1
    assert db.query(Swipe).filter(Swipe.user_id == other.id).count() == 1
