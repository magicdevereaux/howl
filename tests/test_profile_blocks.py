"""GET /api/profile/{user_id} respecting blocks (GAPS #52).

A new file rather than an addition to tests/test_profile.py: that file's
bio-save/regen sections are owned by another agent working in parallel on the
same source file, and this only needs `client`/`db`/`test_user` from conftest.
"""

from app.models.block import Block
from app.models.user import AvatarStatus, User
from app.security import hash_password


def _make_user(db, *, email: str, **kwargs) -> User:
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


def test_profile_blocked_by_target_returns_404(client, db, auth_headers, test_user):
    other = _make_user(db, email="profile_blocker@howl.app")
    db.add(Block(blocker_id=other.id, blocked_id=test_user.id))
    db.commit()

    res = client.get(f"/api/profile/{other.id}", headers=auth_headers)
    assert res.status_code == 404


def test_profile_of_user_i_blocked_returns_404(client, db, auth_headers, test_user):
    other = _make_user(db, email="profile_blocked@howl.app")
    db.add(Block(blocker_id=test_user.id, blocked_id=other.id))
    db.commit()

    res = client.get(f"/api/profile/{other.id}", headers=auth_headers)
    assert res.status_code == 404


def test_profile_block_404_matches_nonexistent_user_body(client, db, auth_headers, test_user):
    """The block case must not be distinguishable from a plain 404."""
    other = _make_user(db, email="profile_indistinguishable@howl.app")
    db.add(Block(blocker_id=test_user.id, blocked_id=other.id))
    db.commit()

    blocked_res = client.get(f"/api/profile/{other.id}", headers=auth_headers)
    missing_res = client.get("/api/profile/99999999", headers=auth_headers)

    assert blocked_res.status_code == missing_res.status_code == 404
    assert blocked_res.json() == missing_res.json()


def test_profile_visible_again_after_unblock(client, db, auth_headers, test_user):
    other = _make_user(db, email="profile_unblocked@howl.app")
    block = Block(blocker_id=test_user.id, blocked_id=other.id)
    db.add(block)
    db.commit()

    assert client.get(f"/api/profile/{other.id}", headers=auth_headers).status_code == 404

    db.delete(block)
    db.commit()

    res = client.get(f"/api/profile/{other.id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["id"] == other.id
