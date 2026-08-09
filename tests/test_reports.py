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
    """If message_id is provided but the message was sent by someone else than
    the reported user, reject -- with the reporter genuinely in the match, so
    this exercises the sender-mismatch branch rather than the membership one."""
    sender = _make_user(db, email="sender3@howl.app")
    unrelated = _make_user(db, email="unrelated3@howl.app")
    match = Match(user1_id=min(test_user.id, sender.id), user2_id=max(test_user.id, sender.id))
    db.add(match)
    db.commit()
    db.refresh(match)
    msg = _make_message(db, match_id=match.id, sender_id=sender.id)

    res = client.post(
        "/api/reports",
        headers=auth_headers,
        # reporting `unrelated`, but the message was sent by `sender`
        json={"reported_user_id": unrelated.id, "reason": "harassment", "message_id": msg.id},
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
# Match membership (GAPS #53)
#
# The old check only compared msg.sender_id to reported_user_id -- it never
# checked that the *reporter* is a participant in that message's match. That
# made 404 (nonexistent id) / 400 (wrong author) / 200 (filed) a three-way
# oracle for message authorship: any account could walk message_id = 1..N
# against a victim and learn exactly which messages they wrote. A reporter who
# isn't in the match must now get the same 404 a nonexistent id gets.
# ---------------------------------------------------------------------------

def test_report_message_from_a_match_you_are_not_in_returns_404(client, db, auth_headers):
    """A real message, genuinely sent by the reported user -- but the reporter
    is a bystander, not a participant. Must not resolve to 200 or 400."""
    victim = _make_user(db, email="victim@howl.app")
    other_party = _make_user(db, email="other_party@howl.app")
    match = Match(user1_id=min(victim.id, other_party.id), user2_id=max(victim.id, other_party.id))
    db.add(match)
    db.commit()
    db.refresh(match)
    msg = _make_message(db, match_id=match.id, sender_id=victim.id)

    res = client.post(
        "/api/reports",
        headers=auth_headers,  # test_user is not in this match at all
        json={"reported_user_id": victim.id, "reason": "harassment", "message_id": msg.id},
    )
    assert res.status_code == 404


def test_report_message_oracle_is_not_distinguishable(client, db, auth_headers):
    """The whole point of #53: 'exists but not yours' and 'does not exist' must
    be the same response, or the endpoint is still an oracle."""
    victim = _make_user(db, email="victim2@howl.app")
    other_party = _make_user(db, email="other_party2@howl.app")
    match = Match(user1_id=min(victim.id, other_party.id), user2_id=max(victim.id, other_party.id))
    db.add(match)
    db.commit()
    db.refresh(match)
    real_msg = _make_message(db, match_id=match.id, sender_id=victim.id)

    not_a_member_res = client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": victim.id, "reason": "harassment", "message_id": real_msg.id},
    )
    nonexistent_res = client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": victim.id, "reason": "harassment", "message_id": 999999},
    )
    assert not_a_member_res.status_code == nonexistent_res.status_code == 404
    assert not_a_member_res.json() == nonexistent_res.json()


def test_report_message_from_your_own_match_still_works(client, db, auth_headers, test_user):
    """The fix must not break the legitimate case: reporting a message from a
    match you are actually part of."""
    other = _make_user(db, email="ownmatch@howl.app")
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


def test_reports_against_different_targets_are_not_deduped(client, db, auth_headers, test_user):
    """Users can still report multiple distinct people."""
    a = _make_user(db, email="multi_a@howl.app")
    b = _make_user(db, email="multi_b@howl.app")
    for target in (a, b):
        res = client.post(
            "/api/reports",
            headers=auth_headers,
            json={"reported_user_id": target.id, "reason": "harassment"},
        )
        assert res.status_code == 200
    assert db.query(Report).filter(Report.reporter_id == test_user.id).count() == 2


# ---------------------------------------------------------------------------
# Dedup / upsert on (reporter_id, reported_user_id, message_id)  (GAPS #53)
#
# Repeating a report against the same target (and, if given, the same
# message) updates the existing row rather than inserting a new one --
# otherwise every probe attempt, successful or not, permanently grows the
# moderation queue GAPS #24 made survive account deletion.
# ---------------------------------------------------------------------------

def test_duplicate_profile_report_updates_existing_row(client, db, auth_headers, test_user):
    """Repeating a report with no message_id against the same target dedups."""
    other = _make_user(db, email="dedup_profile@howl.app")
    for reason in ["fake_profile", "harassment"]:
        res = client.post(
            "/api/reports",
            headers=auth_headers,
            json={"reported_user_id": other.id, "reason": reason},
        )
        assert res.status_code == 200

    reports = db.query(Report).filter(
        Report.reporter_id == test_user.id, Report.reported_user_id == other.id
    ).all()
    assert len(reports) == 1
    assert reports[0].reason == ReportReason.harassment  # the second call won


def test_duplicate_message_report_updates_existing_row(client, db, auth_headers, test_user):
    """Repeating a report citing the same message_id against the same target dedups."""
    other = _make_user(db, email="dedup_message@howl.app")
    match = Match(user1_id=min(test_user.id, other.id), user2_id=max(test_user.id, other.id))
    db.add(match)
    db.commit()
    db.refresh(match)
    msg = _make_message(db, match_id=match.id, sender_id=other.id)

    for reason, notes in [("harassment", "first"), ("spam_scam", "second")]:
        res = client.post(
            "/api/reports",
            headers=auth_headers,
            json={
                "reported_user_id": other.id,
                "reason": reason,
                "notes": notes,
                "message_id": msg.id,
            },
        )
        assert res.status_code == 200

    reports = db.query(Report).filter(Report.message_id == msg.id).all()
    assert len(reports) == 1
    assert reports[0].reason == ReportReason.spam_scam
    assert reports[0].notes == "second"


def test_profile_report_and_message_report_against_same_target_are_distinct(
    client, db, auth_headers, test_user,
):
    """message_id is part of the dedup key -- a profile-level report and a
    message-level report against the same target are different rows."""
    other = _make_user(db, email="dedup_distinct@howl.app")
    match = Match(user1_id=min(test_user.id, other.id), user2_id=max(test_user.id, other.id))
    db.add(match)
    db.commit()
    db.refresh(match)
    msg = _make_message(db, match_id=match.id, sender_id=other.id)

    client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": other.id, "reason": "harassment"},
    )
    client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": other.id, "reason": "spam_scam", "message_id": msg.id},
    )

    assert db.query(Report).filter(Report.reported_user_id == other.id).count() == 2


# ---------------------------------------------------------------------------
# Rate limiting (GAPS #53)
#
# tests/conftest.py keeps the limiter open by default (autouse
# `_open_login_rate_limit` patches `check_rate_limit` to always allow, since
# Redis is real and its keys repeat across tests/runs). Exercising the limiter
# itself means re-patching it here, which the conftest docstring says takes
# precedence because it runs after the fixture.
# ---------------------------------------------------------------------------

def test_report_is_rate_limited_per_account(client, db, auth_headers, test_user, monkeypatch):
    from app.services.rate_limit import _LIMITS

    email_limit = _LIMITS["report"].email_limit
    assert email_limit is not None

    counters: dict[str, int] = {}

    def fake_check_rate_limit(key: str, limit: int, window: int = 900) -> tuple[bool, int]:
        counters[key] = counters.get(key, 0) + 1
        if counters[key] > limit:
            return True, window
        return False, 0

    monkeypatch.setattr("app.services.rate_limit.check_rate_limit", fake_check_rate_limit)

    other = _make_user(db, email="ratelimited@howl.app")
    for _ in range(email_limit):
        res = client.post(
            "/api/reports",
            headers=auth_headers,
            json={"reported_user_id": other.id, "reason": "other"},
        )
        assert res.status_code == 200

    res = client.post(
        "/api/reports",
        headers=auth_headers,
        json={"reported_user_id": other.id, "reason": "other"},
    )
    assert res.status_code == 429
    assert "Retry-After" in res.headers


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
