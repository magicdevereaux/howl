import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models.message import Message
from app.models.report import Report, ReportReason
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportIn(BaseModel):
    reported_user_id: int
    message_id: int | None = None
    reason: ReportReason
    notes: str | None = Field(default=None, max_length=500)


@router.post("", status_code=200)
def submit_report(
    body: ReportIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Submit an abuse report for a user or a specific message."""
    if body.reported_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot report yourself.")

    target = db.query(User).filter(User.id == body.reported_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")

    if body.message_id is not None:
        msg = db.query(Message).filter(Message.id == body.message_id).first()
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found.")
        if msg.sender_id != body.reported_user_id:
            raise HTTPException(
                status_code=400,
                detail="Message does not belong to the reported user.",
            )

    report = Report(
        reporter_id=current_user.id,
        reported_user_id=body.reported_user_id,
        message_id=body.message_id,
        reason=body.reason,
        notes=body.notes or None,
    )
    db.add(report)
    db.commit()

    logger.info(
        "reports: user %d reported user %d reason=%s message=%s",
        current_user.id, body.reported_user_id, body.reason.value,
        body.message_id or "n/a",
    )
    return {"message": "Report submitted. Thank you — our team will review it."}
