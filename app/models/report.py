import enum
from datetime import UTC, datetime

from sqlalchemy import Enum, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import UtcDateTime


class ReportReason(str, enum.Enum):
    spam_scam = "spam_scam"
    inappropriate_content = "inappropriate_content"
    harassment = "harassment"
    fake_profile = "fake_profile"
    underage_user = "underage_user"
    other = "other"


class Report(Base):
    """An abuse report.

    Every foreign key here is ``ON DELETE SET NULL``: a report is moderation
    evidence and outlives the rows it points at.  Deleting the reported user
    (or the reporter, or the reported message) anonymises the report but never
    destroys it, so the ``reason``, ``notes`` and ``created_at`` trail survives.

    This is the resolution of GAPS #24 — the original model claimed reports
    survive message deletion while cascading them away on *user* deletion,
    which meant the one deletion that matters most for moderation, the abuser
    deleting their own account, erased the case against them.  All three FKs now
    agree with the stated intent.  Account deletion still removes all of the
    user's own personal data (users row, swipes, matches, messages); what is
    retained is only the fact that a report was filed and what it said.

    GAPS #53: ``uq_reports_reporter_target_message`` dedups
    ``(reporter_id, reported_user_id, message_id)`` so a duplicate submission
    updates the existing row (see ``app/api/reports.py``) instead of inserting
    a new one -- otherwise the endpoint is an unlimited moderation-queue-filling
    oracle for probing message authorship one id at a time. It is an
    *expression* index keyed on ``COALESCE(message_id, -1)`` rather than a
    plain unique constraint: ordinary SQL treats every NULL as distinct from
    every other NULL, so a bare ``UNIQUE(reporter_id, reported_user_id,
    message_id)`` would never catch two profile-level reports (``message_id``
    NULL) against the same target -- exactly the case that needed catching.
    ``-1`` is a safe sentinel because message ids are positive autoincrement
    integers.

    Deliberately does *not* constrain rows where ``reporter_id`` or
    ``reported_user_id`` is NULL: those are already-anonymised historical
    evidence (see the FK docstring above), not live submissions, and NULL is
    still NULL there — two anonymised reports about unrelated incidents must
    not be forced to collide just because both lost their identifying columns.
    """

    __tablename__ = "reports"
    __table_args__ = (
        Index(
            "uq_reports_reporter_target_message",
            "reporter_id",
            "reported_user_id",
            text("COALESCE(message_id, -1)"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reported_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Indexed: without it every message delete scans reports to apply SET NULL.
    message_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reason: Mapped[ReportReason] = mapped_column(
        Enum(ReportReason, name="report_reason", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<Report reporter={self.reporter_id} reported={self.reported_user_id} reason={self.reason}>"
