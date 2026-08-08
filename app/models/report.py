import enum
from datetime import UTC, datetime

from sqlalchemy import Enum, ForeignKey, Integer, Text, func
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
    """

    __tablename__ = "reports"

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
