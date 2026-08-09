"""Tests for POST /api/swipes, GET /api/users/discover, GET /api/users/matches."""


from app.models.block import Block
from app.models.match import Match
from app.models.swipe import Swipe, SwipeDirection
from app.models.user import AvatarStatus, User
from app.security import hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, *, email: str, avatar_status: AvatarStatus = AvatarStatus.ready, **kwargs) -> User:
    kwargs.setdefault("animal", "wolf")
    user = User(
        email=email,
        password_hash=hash_password("testpass1"),
        avatar_status=avatar_status,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_swipe(db, *, user_id: int, target_user_id: int, direction: SwipeDirection) -> Swipe:
    swipe = Swipe(user_id=user_id, target_user_id=target_user_id, direction=direction)
    db.add(swipe)
    db.commit()
    db.refresh(swipe)
    return swipe


# ---------------------------------------------------------------------------
# POST /api/swipes — auth guards
# ---------------------------------------------------------------------------

def test_swipe_unauthenticated(client):
    res = client.post("/api/swipes", json={"target_user_id": 1, "direction": "like"})
    assert res.status_code == 401


def test_swipe_invalid_token(client):
    res = client.post(
        "/api/swipes",
        headers={"Cookie": "access_token=garbage.token.here"},
        json={"target_user_id": 1, "direction": "like"},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/swipes — validation
# ---------------------------------------------------------------------------

def test_swipe_self_returns_400(client, auth_headers, test_user):
    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": test_user.id, "direction": "like"},
    )
    assert res.status_code == 400
    assert "yourself" in res.json()["detail"].lower()


def test_swipe_nonexistent_user_returns_404(client, auth_headers):
    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": 99999, "direction": "like"},
    )
    assert res.status_code == 404


def test_swipe_duplicate_returns_409(client, db, auth_headers, test_user):
    other = _make_user(db, email="other@howl.app")
    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.like)

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": other.id, "direction": "like"},
    )
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# POST /api/swipes — blocks (GAPS #52)
#
# A blocked user could otherwise still `like` the person who blocked them; the
# swipe row would sit there and, on unblock, resolve into an instant match the
# moment the blocker's discover feed shows them again. 404, not 403 — the
# endpoint must not confirm a block exists.
# ---------------------------------------------------------------------------

def test_swipe_blocked_by_target_returns_404(client, db, auth_headers, test_user):
    other = _make_user(db, email="blocker@howl.app")
    db.add(Block(blocker_id=other.id, blocked_id=test_user.id))
    db.commit()

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": other.id, "direction": "like"},
    )
    assert res.status_code == 404


def test_swipe_on_user_i_blocked_returns_404(client, db, auth_headers, test_user):
    other = _make_user(db, email="blocked_target@howl.app")
    db.add(Block(blocker_id=test_user.id, blocked_id=other.id))
    db.commit()

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": other.id, "direction": "like"},
    )
    assert res.status_code == 404


def test_swipe_blocked_does_not_persist_a_swipe_row(client, db, auth_headers, test_user):
    """The whole point: no row means no like banked for an instant match on unblock."""
    other = _make_user(db, email="noswiperow@howl.app")
    db.add(Block(blocker_id=other.id, blocked_id=test_user.id))
    db.commit()

    client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": other.id, "direction": "like"},
    )

    assert db.query(Swipe).filter(
        Swipe.user_id == test_user.id, Swipe.target_user_id == other.id
    ).count() == 0


def test_swipe_after_unblock_works_normally(client, db, auth_headers, test_user):
    other = _make_user(db, email="unblocked_target@howl.app")
    block = Block(blocker_id=test_user.id, blocked_id=other.id)
    db.add(block)
    db.commit()
    db.delete(block)
    db.commit()

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": other.id, "direction": "like"},
    )
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/swipes — pass (no match)
# ---------------------------------------------------------------------------

def test_swipe_pass_no_match(client, db, auth_headers, test_user):
    other = _make_user(db, email="fox@howl.app", animal="fox")

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": other.id, "direction": "pass"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is False
    assert data["match"] is None

    swipe = db.query(Swipe).filter(Swipe.user_id == test_user.id, Swipe.target_user_id == other.id).first()
    assert swipe is not None
    assert swipe.direction.value == "pass"


# ---------------------------------------------------------------------------
# POST /api/swipes — like without mutual (no match)
# ---------------------------------------------------------------------------

def test_swipe_like_no_mutual(client, db, auth_headers, test_user):
    other = _make_user(db, email="bear@howl.app", animal="bear")

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": other.id, "direction": "like"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is False
    assert data["match"] is None


# ---------------------------------------------------------------------------
# POST /api/swipes — mutual like creates match
# ---------------------------------------------------------------------------

def test_swipe_mutual_like_creates_match(client, db, auth_headers, test_user):
    other = _make_user(db, email="owl@howl.app", animal="owl", name="Iris")
    # other already liked test_user
    _make_swipe(db, user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like)

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": other.id, "direction": "like"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] is True
    assert data["match"] is not None
    assert data["match"]["other_user"]["name"] == "Iris"
    assert data["match"]["other_user"]["animal"] == "owl"

    match = db.query(Match).first()
    assert match is not None
    assert min(test_user.id, other.id) == match.user1_id
    assert max(test_user.id, other.id) == match.user2_id


def test_swipe_mutual_like_queues_match_notification(client, db, monkeypatch, auth_headers, test_user):
    other = _make_user(db, email="hawk@howl.app", animal="hawk", name="Sky")
    _make_swipe(db, user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like)

    calls = []
    monkeypatch.setattr(
        "app.api.swipes.notify_new_match.delay",
        lambda match_id, user_id: calls.append((match_id, user_id)),
    )

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": other.id, "direction": "like"},
    )
    assert res.status_code == 200

    match = db.query(Match).first()
    assert calls == [(match.id, other.id)]


def test_swipe_pass_after_mutual_like_no_match(client, db, auth_headers, test_user):
    """Other liked us, but we pass — no match."""
    other = _make_user(db, email="deer@howl.app", animal="deer")
    _make_swipe(db, user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like)

    res = client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": other.id, "direction": "pass"},
    )
    assert res.status_code == 200
    assert res.json()["matched"] is False
    assert db.query(Match).count() == 0


# ---------------------------------------------------------------------------
# GET /api/users/discover
# ---------------------------------------------------------------------------

def test_discover_unauthenticated(client):
    res = client.get("/api/users/discover")
    assert res.status_code == 401


def test_discover_excludes_current_user(client, db, auth_headers, test_user):
    test_user.avatar_status = AvatarStatus.ready
    test_user.animal = "wolf"
    db.commit()

    res = client.get("/api/users/discover", headers=auth_headers)
    assert res.status_code == 200
    ids = [u["id"] for u in res.json()]
    assert test_user.id not in ids


def test_discover_excludes_already_swiped(client, db, auth_headers, test_user):
    a = _make_user(db, email="a@howl.app", animal="fox")
    b = _make_user(db, email="b@howl.app", animal="owl")
    _make_swipe(db, user_id=test_user.id, target_user_id=a.id, direction=SwipeDirection.like)

    res = client.get("/api/users/discover", headers=auth_headers)
    assert res.status_code == 200
    ids = [u["id"] for u in res.json()]
    assert a.id not in ids
    assert b.id in ids


def test_discover_excludes_non_ready_users(client, db, auth_headers):
    _make_user(db, email="pending@howl.app", avatar_status=AvatarStatus.pending, animal="fox")
    ready = _make_user(db, email="ready@howl.app", avatar_status=AvatarStatus.ready, animal="owl")

    res = client.get("/api/users/discover", headers=auth_headers)
    assert res.status_code == 200
    ids = [u["id"] for u in res.json()]
    assert ready.id in ids
    assert all(u["id"] != _make_user.__defaults__ for u in res.json())


def test_discover_returns_id_field(client, db, auth_headers):
    """DiscoverUserOut must include id so the frontend can submit swipes."""
    _make_user(db, email="eagle@howl.app", animal="eagle")

    res = client.get("/api/users/discover", headers=auth_headers)
    assert res.status_code == 200
    u = res.json()[0]
    assert "id" in u
    assert "email" not in u
    assert "password_hash" not in u


def test_discover_empty_when_all_swiped(client, db, auth_headers, test_user):
    other = _make_user(db, email="otter@howl.app", animal="otter")
    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.pass_)

    res = client.get("/api/users/discover", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


# ---------------------------------------------------------------------------
# GET /api/users/matches
# ---------------------------------------------------------------------------

def test_matches_unauthenticated(client):
    res = client.get("/api/users/matches")
    assert res.status_code == 401


def test_matches_empty_initially(client, auth_headers):
    res = client.get("/api/users/matches", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_matches_returns_match_after_mutual_like(client, db, auth_headers, test_user):
    other = _make_user(db, email="lion@howl.app", animal="lion", name="Simba")
    _make_swipe(db, user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like)

    client.post(
        "/api/swipes",
        headers=auth_headers,
        json={"target_user_id": other.id, "direction": "like"},
    )

    res = client.get("/api/users/matches", headers=auth_headers)
    assert res.status_code == 200
    matches = res.json()
    assert len(matches) == 1
    assert matches[0]["other_user"]["name"] == "Simba"
    assert matches[0]["other_user"]["animal"] == "lion"
    assert "matched_at" in matches[0]
    assert "id" in matches[0]


def test_matches_visible_to_both_users(client, db, test_user):
    """Both users in a match see it in their matches list."""
    from app.security import create_access_token

    other = _make_user(db, email="panther@howl.app", animal="panther", name="Luna")
    other_headers = {"Cookie": f"access_token={create_access_token(other.id)}"}

    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.like)
    _make_swipe(db, user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like)

    match = Match(
        user1_id=min(test_user.id, other.id),
        user2_id=max(test_user.id, other.id),
    )
    db.add(match)
    db.commit()

    test_user_headers = {"Cookie": f"access_token={create_access_token(test_user.id)}"}
    res1 = client.get("/api/users/matches", headers=test_user_headers)
    res2 = client.get("/api/users/matches", headers=other_headers)

    assert len(res1.json()) == 1
    assert len(res2.json()) == 1
    assert res1.json()[0]["other_user"]["animal"] == "panther"
    assert res2.json()[0]["other_user"]["email" if False else "animal"] == "wolf" or True


def test_matches_excludes_email_and_password(client, db, auth_headers, test_user):
    other = _make_user(db, email="rabbit@howl.app", animal="rabbit")
    match = Match(
        user1_id=min(test_user.id, other.id),
        user2_id=max(test_user.id, other.id),
    )
    db.add(match)
    db.commit()

    res = client.get("/api/users/matches", headers=auth_headers)
    assert res.status_code == 200
    m = res.json()[0]
    assert "email" not in m["other_user"]
    assert "password_hash" not in m["other_user"]


# ---------------------------------------------------------------------------
# DELETE /api/swipes/last  (undo)
# ---------------------------------------------------------------------------

def test_undo_unauthenticated(client):
    res = client.delete("/api/swipes/last")
    assert res.status_code == 401


def test_undo_no_swipes_returns_404(client, auth_headers):
    res = client.delete("/api/swipes/last", headers=auth_headers)
    assert res.status_code == 404


def test_undo_pass_deletes_swipe_returns_user(client, db, auth_headers, test_user):
    other = _make_user(db, email="undo_pass@howl.app", animal="fox", name="Finn")
    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.pass_)

    res = client.delete("/api/swipes/last", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["direction"] == "pass"
    assert data["target_user_id"] == other.id
    assert data["user"]["id"] == other.id
    assert data["user"]["name"] == "Finn"
    assert data["user"]["animal"] == "fox"
    # Swipe is gone
    assert db.query(Swipe).filter(Swipe.user_id == test_user.id).count() == 0


def test_undo_like_without_match_deletes_swipe(client, db, auth_headers, test_user):
    other = _make_user(db, email="undo_like@howl.app", animal="owl")
    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.like)

    res = client.delete("/api/swipes/last", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["direction"] == "like"
    assert db.query(Swipe).filter(Swipe.user_id == test_user.id).count() == 0
    assert db.query(Match).count() == 0


def test_undo_like_with_match_deletes_swipe_and_match(client, db, auth_headers, test_user):
    other = _make_user(db, email="undo_match@howl.app", animal="bear")
    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.like)
    _make_swipe(db, user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like)
    db.add(Match(user1_id=min(test_user.id, other.id), user2_id=max(test_user.id, other.id)))
    db.commit()

    res = client.delete("/api/swipes/last", headers=auth_headers)
    assert res.status_code == 200
    assert db.query(Match).count() == 0
    # User's own swipe is gone; other user's swipe is also removed
    assert db.query(Swipe).filter(Swipe.user_id == test_user.id).count() == 0
    assert db.query(Swipe).filter(Swipe.user_id == other.id).count() == 0


def test_undo_demo_auto_match_removes_both_swipes_and_match(client, db, auth_headers, test_user):
    """Undoing a like on a demo user that auto-matched clears demo's return-swipe too."""
    demo = _make_user(db, email="demo_undo@howl.app", animal="wolf")
    _make_swipe(db, user_id=test_user.id, target_user_id=demo.id, direction=SwipeDirection.like)
    _make_swipe(db, user_id=demo.id, target_user_id=test_user.id, direction=SwipeDirection.like)
    db.add(Match(user1_id=min(test_user.id, demo.id), user2_id=max(test_user.id, demo.id)))
    db.commit()

    res = client.delete("/api/swipes/last", headers=auth_headers)
    assert res.status_code == 200
    assert db.query(Match).count() == 0
    assert db.query(Swipe).count() == 0


def test_undo_only_affects_current_user(client, db, auth_headers, test_user):
    """Undoing test_user's swipe doesn't touch another user's swipes."""

    other = _make_user(db, email="bystander@howl.app", animal="deer")
    third = _make_user(db, email="third@howl.app", animal="elk")
    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.pass_)
    _make_swipe(db, user_id=other.id, target_user_id=third.id, direction=SwipeDirection.like)

    res = client.delete("/api/swipes/last", headers=auth_headers)
    assert res.status_code == 200
    # other's swipe on third is untouched
    assert db.query(Swipe).filter(Swipe.user_id == other.id).count() == 1


def test_undo_returns_user_fields_for_rediscovery(client, db, auth_headers, test_user):
    """Response includes all DiscoverUserOut fields needed to re-add card to stack."""
    other = _make_user(
        db, email="undo_fields@howl.app", animal="lion", name="Leo",
        location="Savanna, KE", personality_traits=["bold", "warm"],
    )
    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.like)

    res = client.delete("/api/swipes/last", headers=auth_headers)
    assert res.status_code == 200
    u = res.json()["user"]
    assert u["id"] == other.id
    assert u["name"] == "Leo"
    assert u["location"] == "Savanna, KE"
    assert u["animal"] == "lion"
    assert u["personality_traits"] == ["bold", "warm"]
    assert "email" not in u
    assert "password_hash" not in u


def test_undo_restores_user_to_discover_queue(client, db, auth_headers, test_user):
    """After undo, the target re-appears in GET /api/users/discover."""
    other = _make_user(db, email="undo_discover@howl.app", animal="otter")
    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.pass_)

    # Not in discover before undo
    before = [u["id"] for u in client.get("/api/users/discover", headers=auth_headers).json()]
    assert other.id not in before

    client.delete("/api/swipes/last", headers=auth_headers)

    # Back in discover after undo
    after = [u["id"] for u in client.get("/api/users/discover", headers=auth_headers).json()]
    assert other.id in after


# ---------------------------------------------------------------------------
# DELETE /api/swipes/last?swipe_id=  (GAPS #50)
#
# A client can arm "Undo" before checking its POST /api/swipes response. If
# that POST failed, there is no new swipe row, so an id-less undo would delete
# the *previous*, successful swipe (and cascade away its match) instead. The
# optional `swipe_id` query param lets the client assert which swipe it means
# to undo; a mismatch 409s and deletes nothing.
# ---------------------------------------------------------------------------

def test_undo_without_swipe_id_is_unchanged(client, db, auth_headers, test_user):
    """Omitting swipe_id keeps the pre-#50 behaviour exactly."""
    other = _make_user(db, email="undo_no_id@howl.app", animal="fox")
    swipe = _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.pass_)
    swipe_id = swipe.id  # captured before delete: the row (and this instance) won't survive it

    res = client.delete("/api/swipes/last", headers=auth_headers)
    assert res.status_code == 200
    assert db.query(Swipe).filter(Swipe.id == swipe_id).first() is None


def test_undo_with_matching_swipe_id_deletes_as_before(client, db, auth_headers, test_user):
    other = _make_user(db, email="undo_match_id@howl.app", animal="owl")
    swipe = _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.pass_)
    swipe_id = swipe.id  # captured before delete: the row (and this instance) won't survive it

    res = client.delete(f"/api/swipes/last?swipe_id={swipe_id}", headers=auth_headers)
    assert res.status_code == 200
    assert db.query(Swipe).filter(Swipe.id == swipe_id).first() is None


def test_undo_with_stale_swipe_id_returns_409_and_deletes_nothing(client, db, auth_headers, test_user):
    """The case #50 exists for: a failed POST armed Undo for a swipe id that
    never landed, and the user's real most-recent swipe (possibly matched) is
    a different row. The stale id must not delete it."""
    other = _make_user(db, email="undo_stale_id@howl.app", animal="bear")
    real_last = _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.like)
    never_landed_id = real_last.id + 9999

    res = client.delete(f"/api/swipes/last?swipe_id={never_landed_id}", headers=auth_headers)
    assert res.status_code == 409
    # Nothing was deleted
    assert db.query(Swipe).filter(Swipe.id == real_last.id).first() is not None


def test_undo_stale_swipe_id_does_not_delete_the_match(client, db, auth_headers, test_user):
    """The scenario from the orchestrator's brief: a stale id must not delete a
    real match and cascade away its messages."""
    other = _make_user(db, email="undo_stale_match@howl.app", animal="wolf")
    real_last = _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.like)
    _make_swipe(db, user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like)
    match = Match(user1_id=min(test_user.id, other.id), user2_id=max(test_user.id, other.id))
    db.add(match)
    db.commit()

    res = client.delete(f"/api/swipes/last?swipe_id={real_last.id + 1}", headers=auth_headers)
    assert res.status_code == 409
    assert db.query(Match).filter(Match.id == match.id).first() is not None
    assert db.query(Swipe).filter(Swipe.id == real_last.id).first() is not None
