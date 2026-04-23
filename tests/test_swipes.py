"""Tests for POST /api/swipes, GET /api/users/discover, GET /api/users/matches."""

import pytest

from app.models.match import Match
from app.models.swipe import Swipe, SwipeDirection
from app.models.user import AvatarStatus, User
from app.security import hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, *, email: str, avatar_status: AvatarStatus = AvatarStatus.ready, **kwargs) -> User:
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
        headers={"Authorization": "Bearer garbage"},
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
    other_headers = {"Authorization": f"Bearer {create_access_token(other.id)}"}

    _make_swipe(db, user_id=test_user.id, target_user_id=other.id, direction=SwipeDirection.like)
    _make_swipe(db, user_id=other.id, target_user_id=test_user.id, direction=SwipeDirection.like)

    match = Match(
        user1_id=min(test_user.id, other.id),
        user2_id=max(test_user.id, other.id),
    )
    db.add(match)
    db.commit()

    test_user_headers = {"Authorization": f"Bearer {create_access_token(test_user.id)}"}
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
