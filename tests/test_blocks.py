"""Tests for block/unblock, unmatch, and discover filtering."""

import pytest

from app.models.block import Block
from app.models.match import Match
from app.models.message import Message
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


def _make_match(db, a: User, b: User) -> Match:
    m = Match(user1_id=min(a.id, b.id), user2_id=max(a.id, b.id))
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _make_swipe(db, *, from_id: int, to_id: int, direction=SwipeDirection.like) -> Swipe:
    s = Swipe(user_id=from_id, target_user_id=to_id, direction=direction)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# POST /api/blocks
# ---------------------------------------------------------------------------

def test_block_unauthenticated(client):
    res = client.post("/api/blocks", json={"blocked_id": 1})
    assert res.status_code == 401


def test_block_creates_record(client, db, test_user):
    other = _make_user(db, email="other@howl.app")
    res = client.post("/api/blocks", headers=_headers(test_user), json={"blocked_id": other.id})
    assert res.status_code == 201
    assert db.query(Block).filter(Block.blocker_id == test_user.id, Block.blocked_id == other.id).count() == 1


def test_block_self_returns_400(client, test_user):
    res = client.post("/api/blocks", headers=_headers(test_user), json={"blocked_id": test_user.id})
    assert res.status_code == 400


def test_block_nonexistent_user_returns_404(client, test_user):
    res = client.post("/api/blocks", headers=_headers(test_user), json={"blocked_id": 99999})
    assert res.status_code == 404


def test_block_duplicate_returns_409(client, db, test_user):
    other = _make_user(db, email="other2@howl.app")
    client.post("/api/blocks", headers=_headers(test_user), json={"blocked_id": other.id})
    res = client.post("/api/blocks", headers=_headers(test_user), json={"blocked_id": other.id})
    assert res.status_code == 409


def test_block_removes_existing_match(client, db, test_user):
    other = _make_user(db, email="other3@howl.app")
    match = _make_match(db, test_user, other)
    match_id = match.id

    client.post("/api/blocks", headers=_headers(test_user), json={"blocked_id": other.id})

    assert db.query(Match).filter(Match.id == match_id).first() is None


def test_block_removes_mutual_swipes(client, db, test_user):
    other = _make_user(db, email="other4@howl.app")
    _make_swipe(db, from_id=test_user.id, to_id=other.id)
    _make_swipe(db, from_id=other.id, to_id=test_user.id)

    client.post("/api/blocks", headers=_headers(test_user), json={"blocked_id": other.id})

    remaining = db.query(Swipe).filter(
        ((Swipe.user_id == test_user.id) & (Swipe.target_user_id == other.id)) |
        ((Swipe.user_id == other.id) & (Swipe.target_user_id == test_user.id))
    ).count()
    assert remaining == 0


# ---------------------------------------------------------------------------
# DELETE /api/blocks/{blocked_id}
# ---------------------------------------------------------------------------

def test_unblock_unauthenticated(client):
    res = client.delete("/api/blocks/1")
    assert res.status_code == 401


def test_unblock_removes_record(client, db, test_user):
    other = _make_user(db, email="other5@howl.app")
    db.add(Block(blocker_id=test_user.id, blocked_id=other.id))
    db.commit()

    res = client.delete(f"/api/blocks/{other.id}", headers=_headers(test_user))
    assert res.status_code == 204
    assert db.query(Block).filter(Block.blocker_id == test_user.id, Block.blocked_id == other.id).count() == 0


def test_unblock_not_blocked_returns_404(client, db, test_user):
    other = _make_user(db, email="other6@howl.app")
    res = client.delete(f"/api/blocks/{other.id}", headers=_headers(test_user))
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/blocks
# ---------------------------------------------------------------------------

def test_list_blocks_unauthenticated(client):
    res = client.get("/api/blocks")
    assert res.status_code == 401


def test_list_blocks_empty(client, test_user):
    res = client.get("/api/blocks", headers=_headers(test_user))
    assert res.status_code == 200
    assert res.json() == []


def test_list_blocks_returns_blocked_users(client, db, test_user):
    other = _make_user(db, email="listed@howl.app", name="Blocked User", animal="fox")
    db.add(Block(blocker_id=test_user.id, blocked_id=other.id))
    db.commit()

    res = client.get("/api/blocks", headers=_headers(test_user))
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["id"] == other.id
    assert data[0]["name"] == "Blocked User"
    assert data[0]["animal"] == "fox"
    assert "email" not in data[0]
    assert "password_hash" not in data[0]


def test_list_blocks_only_returns_own_blocks(client, db, test_user):
    a = _make_user(db, email="a@howl.app")
    b = _make_user(db, email="b@howl.app")
    # test_user blocks a; b blocks a (should not appear for test_user)
    db.add(Block(blocker_id=test_user.id, blocked_id=a.id))
    db.add(Block(blocker_id=b.id, blocked_id=a.id))
    db.commit()

    res = client.get("/api/blocks", headers=_headers(test_user))
    assert len(res.json()) == 1
    assert res.json()[0]["id"] == a.id


# ---------------------------------------------------------------------------
# DELETE /api/matches/{match_id} (unmatch)
# ---------------------------------------------------------------------------

def test_unmatch_unauthenticated(client, db, test_user):
    other = _make_user(db, email="um@howl.app")
    m = _make_match(db, test_user, other)
    res = client.delete(f"/api/matches/{m.id}")
    assert res.status_code == 401


def test_unmatch_not_in_match_returns_403(client, db, test_user):
    a = _make_user(db, email="a2@howl.app")
    b = _make_user(db, email="b2@howl.app")
    m = _make_match(db, a, b)
    res = client.delete(f"/api/matches/{m.id}", headers=_headers(test_user))
    assert res.status_code == 403


def test_unmatch_removes_match_and_messages(client, db, test_user):
    other = _make_user(db, email="um2@howl.app")
    m = _make_match(db, test_user, other)
    match_id = m.id
    msg = Message(match_id=match_id, sender_id=test_user.id, content="hi")
    db.add(msg)
    db.commit()

    res = client.delete(f"/api/matches/{match_id}", headers=_headers(test_user))
    assert res.status_code == 204
    assert db.query(Match).filter(Match.id == match_id).first() is None
    assert db.query(Message).filter(Message.match_id == match_id).count() == 0


def test_unmatch_removes_both_swipes(client, db, test_user):
    other = _make_user(db, email="um3@howl.app")
    _make_swipe(db, from_id=test_user.id, to_id=other.id)
    _make_swipe(db, from_id=other.id, to_id=test_user.id)
    m = _make_match(db, test_user, other)

    client.delete(f"/api/matches/{m.id}", headers=_headers(test_user))

    remaining = db.query(Swipe).filter(
        ((Swipe.user_id == test_user.id) & (Swipe.target_user_id == other.id)) |
        ((Swipe.user_id == other.id) & (Swipe.target_user_id == test_user.id))
    ).count()
    assert remaining == 0


def test_unmatched_user_reappears_in_discover(client, db, test_user):
    other = _make_user(db, email="um4@howl.app")
    _make_swipe(db, from_id=test_user.id, to_id=other.id)
    _make_swipe(db, from_id=other.id, to_id=test_user.id)
    m = _make_match(db, test_user, other)

    # Before unmatch: other not in discover (already swiped)
    before = [u["id"] for u in client.get("/api/users/discover", headers=_headers(test_user)).json()]
    assert other.id not in before

    client.delete(f"/api/matches/{m.id}", headers=_headers(test_user))

    # After unmatch: other reappears
    after = [u["id"] for u in client.get("/api/users/discover", headers=_headers(test_user)).json()]
    assert other.id in after


# ---------------------------------------------------------------------------
# Discover filtering
# ---------------------------------------------------------------------------

def test_discover_excludes_users_i_blocked(client, db, test_user):
    other = _make_user(db, email="excl@howl.app")
    db.add(Block(blocker_id=test_user.id, blocked_id=other.id))
    db.commit()

    ids = [u["id"] for u in client.get("/api/users/discover", headers=_headers(test_user)).json()]
    assert other.id not in ids


def test_discover_excludes_users_who_blocked_me(client, db, test_user):
    other = _make_user(db, email="excl2@howl.app")
    db.add(Block(blocker_id=other.id, blocked_id=test_user.id))
    db.commit()

    ids = [u["id"] for u in client.get("/api/users/discover", headers=_headers(test_user)).json()]
    assert other.id not in ids


def test_unblock_restores_discoverability(client, db, test_user):
    other = _make_user(db, email="excl3@howl.app")
    db.add(Block(blocker_id=test_user.id, blocked_id=other.id))
    db.commit()

    before = [u["id"] for u in client.get("/api/users/discover", headers=_headers(test_user)).json()]
    assert other.id not in before

    client.delete(f"/api/blocks/{other.id}", headers=_headers(test_user))

    after = [u["id"] for u in client.get("/api/users/discover", headers=_headers(test_user)).json()]
    assert other.id in after
