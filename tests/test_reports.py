"""Tests for POST /api/reports."""

import pytest

from app.models.match import Match
from app.models.message import Message
from app.models.report import Report, ReportReason
from app.models.user import AvatarStatus, User
from app.security import hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _make_message(db, *, match_id: int, sender_id: int, content: str = "hi") -> Message:
    msg = Message(match_id=match_id, sender_id=sender_id, content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_report_unauthenticated(client):
    res = client.post("/api/reports", json={"reported_user_id": 1, "reason": "other"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_report_self_returns_400(client, auth_headers, test_user):
    res = client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": test_user.id, "reason": "other"},
    )
    assert res.status_code == 400


def test_report_nonexistent_user_returns_404(client, auth_headers):
    res = client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": 99999, "reason": "spam_scam"},
    )
    assert res.status_code == 404


def test_report_invalid_reason_returns_422(client, db, auth_headers):
    other = _make_user(db, email="other@howl.app")
    res = client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": other.id, "reason": "not_a_real_reason"},
    )
    assert res.status_code == 422


def test_report_notes_too_long_returns_422(client, db, auth_headers):
    other = _make_user(db, email="other2@howl.app")
    res = client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": other.id, "reason": "other", "notes": "x" * 501},
    )
    assert res.status_code == 422


def test_report_message_not_belonging_to_reported_user_returns_400(client, db, auth_headers, test_user):
    """If message_id is provided but the message was sent by someone else, reject."""
    other = _make_user(db, email="other3@howl.app")
    third = _make_user(db, email="third@howl.app")
    match = Match(user1_id=min(other.id, third.id), user2_id=max(other.id, third.id))
    db.add(match)
    db.commit()
    db.refresh(match)
    msg = _make_message(db, match_id=match.id, sender_id=third.id)

    res = client.post(
        "/api/reports",
        headers=auth_headers,
        # reporting `other` but message was sent by `third`
        json={"reported_user_id": other.id, "reason": "harassment", "message_id": msg.id},
    )
    assert res.status_code == 400


def test_report_nonexistent_message_returns_404(client, db, auth_headers):
    other = _make_user(db, email="other4@howl.app")
    res = client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": other.id, "reason": "harassment", "message_id": 99999},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Success: profile report
# ---------------------------------------------------------------------------

def test_profile_report_returns_200(client, db, auth_headers):
    other = _make_user(db, email="reported@howl.app")
    res = client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": other.id, "reason": "fake_profile"},
    )
    assert res.status_code == 200
    assert "report" in res.json()["message"].lower()


def test_profile_report_stored_in_db(client, db, auth_headers, test_user):
    other = _make_user(db, email="reported2@howl.app")
    client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": other.id, "reason": "spam_scam", "notes": "Sending links"},
    )
    report = db.query(Report).filter(
        Report.reporter_id == test_user.id,
        Report.reported_user_id == other.id,
    ).first()
    assert report is not None
    assert report.reason == ReportReason.spam_scam
    assert report.notes == "Sending links"
    assert report.message_id is None


def test_profile_report_all_reasons_accepted(client, db, auth_headers):
    other = _make_user(db, email="reported3@howl.app")
    for reason in ReportReason:
        res = client.post(
            "/api/reports",
            headers=auth_headers,
            json={"reported_user_id": other.id, "reason": reason.value},
        )
        assert res.status_code == 200, f"reason {reason.value} should be accepted"


# ---------------------------------------------------------------------------
# Success: message report
# ---------------------------------------------------------------------------

def test_message_report_returns_200(client, db, auth_headers, test_user):
    other = _make_user(db, email="sender@howl.app")
    match = Match(user1_id=min(test_user.id, other.id), user2_id=max(test_user.id, other.id))
    db.add(match)
    db.commit()
    db.refresh(match)
    msg = _make_message(db, match_id=match.id, sender_id=other.id)

    res = client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": other.id, "reason": "harassment", "message_id": msg.id},
    )
    assert res.status_code == 200


def test_message_report_stored_in_db(client, db, auth_headers, test_user):
    other = _make_user(db, email="sender2@howl.app")
    match = Match(user1_id=min(test_user.id, other.id), user2_id=max(test_user.id, other.id))
    db.add(match)
    db.commit()
    db.refresh(match)
    msg = _make_message(db, match_id=match.id, sender_id=other.id, content="Bad message")
    msg_id = msg.id

    client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": other.id, "reason": "inappropriate_content", "message_id": msg_id},
    )

    report = db.query(Report).filter(Report.reporter_id == test_user.id).first()
    assert report is not None
    assert report.message_id == msg_id
    assert report.reason == ReportReason.inappropriate_content


def test_report_without_notes_stores_null(client, db, auth_headers, test_user):
    other = _make_user(db, email="quiet@howl.app")
    client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": other.id, "reason": "other"},
    )
    report = db.query(Report).filter(Report.reporter_id == test_user.id).first()
    assert report.notes is None


def test_multiple_reports_allowed(client, db, auth_headers, test_user):
    """Users can submit multiple reports (e.g. user + individual message)."""
    other = _make_user(db, email="multi@howl.app")
    for reason in ["fake_profile", "harassment"]:
        client.post(
            "/api/reports",
            headers=auth_headers,
            json={"reported_user_id": other.id, "reason": reason},
        )
    assert db.query(Report).filter(Report.reporter_id == test_user.id).count() == 2
