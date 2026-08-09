"""POST /api/auth/change-email — the repair path email verification was missing.

Before this endpoint, `email` was editable nowhere: `ProfileUpdate` has no such
field, so resend-verification could only ever re-send to the address typed at
signup. With verification enforced after a 72h grace window (GAPS #25), one
typo at registration was a permanent lockout — no link, no way to fix the
address, no admin route. The operator kill switch was the only remedy.
"""

import pytest

from app.models.user import AvatarStatus, User
from app.security import create_access_token, hash_password, verify_password

PASSWORD = "hunter2secure"


@pytest.fixture()
def owner(db) -> User:
    user = User(
        email="typo@howl.app",
        password_hash=hash_password(PASSWORD),
        avatar_status=AvatarStatus.pending,
        is_email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def owner_headers(owner: User) -> dict[str, str]:
    return {"Cookie": f"access_token={create_access_token(owner.id)}"}


@pytest.fixture(autouse=True)
def _capture_emails(monkeypatch):
    """Both sends are side effects we assert on; neither should reach a provider."""
    sent: dict[str, list] = {"verification": [], "notice": []}
    monkeypatch.setattr(
        "app.services.auth_service.send_verification_email",
        lambda to, token: sent["verification"].append((to, token)),
    )
    monkeypatch.setattr(
        "app.services.auth_service.send_email_changed_notice",
        lambda old, new: sent["notice"].append((old, new)),
    )
    return sent


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------

def test_change_email_moves_the_account_and_resets_verification(
    client, db, owner, owner_headers, _capture_emails
):
    res = client.post(
        "/api/auth/change-email",
        json={"new_email": "correct@howl.app", "current_password": PASSWORD},
        headers=owner_headers,
    )

    assert res.status_code == 200, res.text
    assert res.json()["email"] == "correct@howl.app"
    assert res.json()["is_email_verified"] is False

    db.refresh(owner)
    assert owner.email == "correct@howl.app"
    # The new address is unverified: it has not been proven to belong to anyone.
    assert owner.is_email_verified is False
    assert owner.email_verification_token is not None


def test_the_verification_link_goes_to_the_new_address(
    client, owner, owner_headers, _capture_emails
):
    """The whole point — resend-verification could only ever mail the typo."""
    client.post(
        "/api/auth/change-email",
        json={"new_email": "correct@howl.app", "current_password": PASSWORD},
        headers=owner_headers,
    )
    assert [to for to, _ in _capture_emails["verification"]] == ["correct@howl.app"]


def test_the_old_address_is_warned(client, owner, owner_headers, _capture_emails):
    """If someone with the password moves the account, this is the owner's only signal."""
    client.post(
        "/api/auth/change-email",
        json={"new_email": "attacker@notmine.app", "current_password": PASSWORD},
        headers=owner_headers,
    )
    assert _capture_emails["notice"] == [("typo@howl.app", "attacker@notmine.app")]


def test_the_new_address_is_normalised(client, db, owner, owner_headers):
    client.post(
        "/api/auth/change-email",
        json={"new_email": "  MiXeD@Howl.App  ", "current_password": PASSWORD},
        headers=owner_headers,
    )
    db.refresh(owner)
    assert owner.email == "mixed@howl.app"


def test_the_new_address_can_then_be_verified(client, db, owner, owner_headers):
    """End to end: the repair path actually repairs."""
    client.post(
        "/api/auth/change-email",
        json={"new_email": "correct@howl.app", "current_password": PASSWORD},
        headers=owner_headers,
    )
    db.refresh(owner)

    res = client.post(
        "/api/auth/verify-email", json={"token": owner.email_verification_token}
    )
    assert res.status_code == 200

    db.refresh(owner)
    assert owner.is_email_verified is True


# ---------------------------------------------------------------------------
# Authentication and authorisation
# ---------------------------------------------------------------------------

def test_a_session_alone_is_not_enough(client, db, owner, owner_headers, _capture_emails):
    """A stolen token must not be able to move the account.

    Moving the address hands over the password-reset channel, which is the whole
    account — so this requires re-proving the password, not merely a live session.
    """
    res = client.post(
        "/api/auth/change-email",
        json={"new_email": "attacker@notmine.app", "current_password": "wrong-password"},
        headers=owner_headers,
    )

    assert res.status_code == 403
    db.refresh(owner)
    assert owner.email == "typo@howl.app"
    assert owner.is_email_verified is True
    assert _capture_emails["verification"] == []
    assert _capture_emails["notice"] == []


def test_403_not_401_so_clients_do_not_bounce_to_login(client, owner, owner_headers):
    """Both clients' interceptors treat 401 as an expired session."""
    res = client.post(
        "/api/auth/change-email",
        json={"new_email": "x@howl.app", "current_password": "wrong-password"},
        headers=owner_headers,
    )
    assert res.status_code == 403


def test_unauthenticated_requests_are_rejected(client):
    res = client.post(
        "/api/auth/change-email",
        json={"new_email": "x@howl.app", "current_password": PASSWORD},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Conflicts and no-ops
# ---------------------------------------------------------------------------

def test_an_address_already_in_use_is_a_409(client, db, owner, owner_headers):
    db.add(User(email="taken@howl.app", password_hash=hash_password(PASSWORD)))
    db.commit()

    res = client.post(
        "/api/auth/change-email",
        json={"new_email": "taken@howl.app", "current_password": PASSWORD},
        headers=owner_headers,
    )

    assert res.status_code == 409
    db.refresh(owner)
    # The rollback must leave verification intact — a failed change that
    # nonetheless un-verified the account would be its own lockout.
    assert owner.email == "typo@howl.app"
    assert owner.is_email_verified is True


def test_changing_to_the_same_address_is_rejected(client, db, owner, owner_headers):
    res = client.post(
        "/api/auth/change-email",
        json={"new_email": "typo@howl.app", "current_password": PASSWORD},
        headers=owner_headers,
    )
    assert res.status_code == 400
    db.refresh(owner)
    assert owner.is_email_verified is True


def test_the_password_is_not_disturbed(client, db, owner, owner_headers):
    client.post(
        "/api/auth/change-email",
        json={"new_email": "correct@howl.app", "current_password": PASSWORD},
        headers=owner_headers,
    )
    db.refresh(owner)
    assert verify_password(PASSWORD, owner.password_hash)
