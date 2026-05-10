"""Tests for preference fields and preference-based discover filtering."""

import pytest

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
        animal="wolf",
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _h(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


# ---------------------------------------------------------------------------
# Profile PATCH — preference fields
# ---------------------------------------------------------------------------

def test_patch_gender_accepted(client, auth_headers):
    for g in ("man", "woman", "non-binary", "other"):
        res = client.patch("/api/profile/me", headers=auth_headers, json={"gender": g})
        assert res.status_code == 200
        assert res.json()["gender"] == g


def test_patch_gender_invalid_rejected(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"gender": "alien"})
    assert res.status_code == 422


def test_patch_sexuality_accepted(client, auth_headers):
    for s in ("straight", "gay", "lesbian", "bisexual", "pansexual", "other"):
        res = client.patch("/api/profile/me", headers=auth_headers, json={"sexuality": s})
        assert res.status_code == 200
        assert res.json()["sexuality"] == s


def test_patch_sexuality_invalid_rejected(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"sexuality": "confused"})
    assert res.status_code == 422


def test_patch_looking_for_accepted(client, auth_headers):
    for lf in ("men", "women", "non-binary", "everyone"):
        res = client.patch("/api/profile/me", headers=auth_headers, json={"looking_for": lf})
        assert res.status_code == 200
        assert res.json()["looking_for"] == lf


def test_patch_looking_for_invalid_rejected(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"looking_for": "robots"})
    assert res.status_code == 422


def test_patch_age_preference_range(client, auth_headers):
    res = client.patch(
        "/api/profile/me", headers=auth_headers,
        json={"age_preference_min": 25, "age_preference_max": 40},
    )
    assert res.status_code == 200
    assert res.json()["age_preference_min"] == 25
    assert res.json()["age_preference_max"] == 40


def test_patch_age_preference_min_below_18_rejected(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"age_preference_min": 17})
    assert res.status_code == 422


def test_patch_age_preference_max_above_120_rejected(client, auth_headers):
    res = client.patch("/api/profile/me", headers=auth_headers, json={"age_preference_max": 121})
    assert res.status_code == 422


def test_preference_fields_default_null(client, auth_headers):
    res = client.get("/api/profile/me", headers=auth_headers)
    data = res.json()
    assert data["gender"] is None
    assert data["sexuality"] is None
    assert data["looking_for"] is None
    assert data["age_preference_min"] is None
    assert data["age_preference_max"] is None


# ---------------------------------------------------------------------------
# Discover — no filtering when preferences are unset
# ---------------------------------------------------------------------------

def test_discover_no_filter_when_prefs_null(client, db, test_user):
    man = _make_user(db, email="man@howl.app", gender="man", age=30)
    woman = _make_user(db, email="woman@howl.app", gender="woman", age=25)
    nobody = _make_user(db, email="nobody@howl.app")  # no gender, no age

    ids = [u["id"] for u in client.get("/api/users/discover", headers=_h(test_user)).json()]
    assert man.id in ids
    assert woman.id in ids
    assert nobody.id in ids


# ---------------------------------------------------------------------------
# Discover — age preference filtering
# ---------------------------------------------------------------------------

def test_discover_filters_by_age_min(client, db, test_user):
    test_user.age_preference_min = 30
    db.commit()

    young = _make_user(db, email="young@howl.app", age=25)
    old = _make_user(db, email="old@howl.app", age=35)
    no_age = _make_user(db, email="noage@howl.app")

    ids = [u["id"] for u in client.get("/api/users/discover", headers=_h(test_user)).json()]
    assert young.id not in ids   # 25 < 30
    assert old.id in ids          # 35 >= 30
    assert no_age.id in ids       # null age always included


def test_discover_filters_by_age_max(client, db, test_user):
    test_user.age_preference_max = 35
    db.commit()

    young = _make_user(db, email="young2@howl.app", age=25)
    old = _make_user(db, email="old2@howl.app", age=40)
    no_age = _make_user(db, email="noage2@howl.app")

    ids = [u["id"] for u in client.get("/api/users/discover", headers=_h(test_user)).json()]
    assert young.id in ids        # 25 <= 35
    assert old.id not in ids      # 40 > 35
    assert no_age.id in ids       # null age always included


def test_discover_filters_by_age_range(client, db, test_user):
    test_user.age_preference_min = 25
    test_user.age_preference_max = 35
    db.commit()

    too_young = _make_user(db, email="ty@howl.app", age=22)
    in_range = _make_user(db, email="ir@howl.app", age=30)
    too_old = _make_user(db, email="to@howl.app", age=40)

    ids = [u["id"] for u in client.get("/api/users/discover", headers=_h(test_user)).json()]
    assert too_young.id not in ids
    assert in_range.id in ids
    assert too_old.id not in ids


# ---------------------------------------------------------------------------
# Discover — looking_for / gender filtering
# ---------------------------------------------------------------------------

def test_discover_filters_by_looking_for_men(client, db, test_user):
    test_user.looking_for = "men"
    db.commit()

    man = _make_user(db, email="man2@howl.app", gender="man")
    woman = _make_user(db, email="woman2@howl.app", gender="woman")
    no_gender = _make_user(db, email="ng@howl.app")

    ids = [u["id"] for u in client.get("/api/users/discover", headers=_h(test_user)).json()]
    assert man.id in ids
    assert woman.id not in ids    # gender doesn't match
    assert no_gender.id in ids    # null gender always included


def test_discover_filters_by_looking_for_women(client, db, test_user):
    test_user.looking_for = "women"
    db.commit()

    man = _make_user(db, email="man3@howl.app", gender="man")
    woman = _make_user(db, email="woman3@howl.app", gender="woman")

    ids = [u["id"] for u in client.get("/api/users/discover", headers=_h(test_user)).json()]
    assert man.id not in ids
    assert woman.id in ids


def test_discover_everyone_shows_all_genders(client, db, test_user):
    test_user.looking_for = "everyone"
    db.commit()

    man = _make_user(db, email="man4@howl.app", gender="man")
    woman = _make_user(db, email="woman4@howl.app", gender="woman")
    nb = _make_user(db, email="nb@howl.app", gender="non-binary")

    ids = [u["id"] for u in client.get("/api/users/discover", headers=_h(test_user)).json()]
    assert man.id in ids
    assert woman.id in ids
    assert nb.id in ids


def test_discover_null_looking_for_shows_all(client, db, test_user):
    """looking_for = null (unset) behaves identically to 'everyone'."""
    assert test_user.looking_for is None

    man = _make_user(db, email="man5@howl.app", gender="man")
    woman = _make_user(db, email="woman5@howl.app", gender="woman")

    ids = [u["id"] for u in client.get("/api/users/discover", headers=_h(test_user)).json()]
    assert man.id in ids
    assert woman.id in ids
