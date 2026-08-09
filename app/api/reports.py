import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.match import Match
from app.models.message import Message
from app.models.report import Report, ReportReason
from app.models.user import User
from app.services.rate_limit import enforce_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])

_MESSAGE_NOT_FOUND = "Message not found."


class ReportIn(BaseModel):
    reported_user_id: int
    message_id: int | None = None
    reason: ReportReason
    notes: str | None = Field(default=None, max_length=500)


@router.post("", status_code=200)
def submit_report(
    body: ReportIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Submit an abuse report for a user or a specific message.

    GAPS #53: this used to validate a submitted ``message_id`` by loading the
    message and checking ``msg.sender_id != reported_user_id`` without ever
    checking that *the reporter* is a participant in that message's match. The
    three outcomes -- 404 nonexistent id, 400 wrong author, 200 filed -- were
    distinguishable, so any authenticated account could walk
    ``message_id = 1..N`` against a chosen victim and learn exactly which
    messages they wrote (the private social graph, via ``created_at``)
    without ever reading content. Requiring match membership and collapsing
    "not found" and "not yours" into the same 404 closes that. The rate limit
    and the DB-level dedup (see the Report model and its migration) close the
    two multipliers: unlimited attempts, and every attempt permanently
    growing the moderation queue.
    """
    enforce_rate_limit(request, "report", email=current_user.email)

    if body.reported_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot report yourself.")

    target = db.query(User).filter(User.id == body.reported_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    if body.message_id is not None:
        msg = db.query(Message).filter(Message.id == body.message_id).first()
        if msg is None:
            raise HTTPException(status_code=404, detail=_MESSAGE_NOT_FOUND)

        match = db.query(Match).filter(Match.id == msg.match_id).first()
        is_member = match is not None and current_user.id in (match.user1_id, match.user2_id)
        if not is_member:
            # Same response as "message not found" -- a reporter who isn't in
            # the match must not be able to tell the difference between a
            # message that doesn't exist and one that isn't theirs to cite.
            raise HTTPException(status_code=404, detail=_MESSAGE_NOT_FOUND)

        if msg.sender_id != body.reported_user_id:
            raise HTTPException(
                status_code=400,
                detail="Message does not belong to the reported user.",
            )

    # Dedup on (reporter_id, reported_user_id, message_id) via
    # uq_reports_reporter_target_message: a repeat submission against the same
    # target (and, if given, the same message) updates the existing row's
    # reason/notes/created_at rather than inserting a new one. Same
    # SAVEPOINT-then-recover shape as app/api/swipes.py's duplicate-swipe
    # handling, since SQLite (the test suite) only enforces the constraint
    # inside a real transaction.
    report = Report(
        reporter_id=current_user.id,
        reported_user_id=body.reported_user_id,
        message_id=body.message_id,
        reason=body.reason,
        notes=body.notes or None,
    )
    try:
        with db.begin_nested():
            db.add(report)
            db.flush()
    except IntegrityError:
        message_filter = (
            Report.message_id.is_(None)
            if body.message_id is None
            else Report.message_id == body.message_id
        )
        existing = (
            db.query(Report)
            .filter(
                Report.reporter_id == current_user.id,
                Report.reported_user_id == body.reported_user_id,
                message_filter,
            )
            .first()
        )
        if existing is None:
            raise
        existing.reason = body.reason
        existing.notes = body.notes or None
        existing.created_at = datetime.now(UTC)
        logger.info(
            "reports: user %d updated an existing report (id=%d) against user %d message=%s",
            current_user.id, existing.id, body.reported_user_id, body.message_id or "n/a",
        )

    db.commit()

    logger.info(
        "reports: user %d reported user %d reason=%s message=%s",
        current_user.id, body.reported_user_id, body.reason.value,
        body.message_id or "n/a",
    )
    return {"message": "Report submitted. Thank you — our team will review it."}
