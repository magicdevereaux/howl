"""Tests for POST /api/reports."""


from app.models.match import Match
from app.models.message import Message
from app.models.report import Report, ReportReason
from app.models.user import AvatarStatus, User
from app.security import hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Report survival  (GAPS #24)
#
# A report is moderation evidence and outlives the rows it points at.  Every FK
# is ON DELETE SET NULL, so a deletion anonymises the report but never destroys
# it.  Before this, reporter_id and reported_user_id cascaded, which meant an
# abuser deleting their own account erased the case against them.
# ---------------------------------------------------------------------------

def test_report_survives_the_reported_user_being_deleted(client, db, auth_headers, test_user):
    abuser = _make_user(db, email="abuser@howl.app")
    client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": abuser.id, "reason": "harassment", "notes": "kept as evidence"},
    )
    report_id = db.query(Report.id).scalar()
    assert report_id is not None

    db.delete(abuser)
    db.commit()
    db.expire_all()

    report = db.get(Report, report_id)
    assert report is not None, "deleting the reported user destroyed the report"
    assert report.reported_user_id is None      # anonymised
    assert report.reporter_id == test_user.id   # the reporter is still known
    assert report.reason == ReportReason.harassment
    assert report.notes == "kept as evidence"   # the evidence itself is intact


def test_report_survives_the_reporter_being_deleted(client, db, auth_headers, test_user):
    abuser = _make_user(db, email="abuser2@howl.app")
    client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": abuser.id, "reason": "spam_scam"},
    )
    report_id = db.query(Report.id).scalar()

    db.delete(db.get(User, test_user.id))
    db.commit()
    db.expire_all()

    report = db.get(Report, report_id)
    assert report is not None, "deleting the reporter destroyed the report"
    assert report.reporter_id is None
    assert report.reported_user_id == abuser.id


def test_report_survives_the_message_being_deleted(client, db, auth_headers, test_user):
    """The one FK that was already SET NULL — kept covered so it stays that way."""
    other = _make_user(db, email="msgabuser@howl.app")
    match = Match(user1_id=min(test_user.id, other.id), user2_id=max(test_user.id, other.id))
    db.add(match)
    db.commit()
    msg = _make_message(db, match_id=match.id, sender_id=other.id, content="bad thing")

    client.post(
        "/api/reports",
        headers=auth_headers,
        json={
            "reported_user_id": other.id,
            "reason": "inappropriate_content",
            "message_id": msg.id,
        },
    )
    report_id = db.query(Report.id).scalar()

    db.delete(db.get(Message, msg.id))
    db.commit()
    db.expire_all()

    report = db.get(Report, report_id)
    assert report is not None
    assert report.message_id is None
    assert report.reason == ReportReason.inappropriate_content
