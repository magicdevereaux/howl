import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReportReason(str, enum.Enum):
    spam_scam = "spam_scam"
    inappropriate_content = "inappropriate_content"
    harassment = "harassment"
    fake_profile = "fake_profile"
    underage_user = "underage_user"
    other = "other"


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reporter_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reported_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL so reports survive message deletion (e.g. after an unmatch)
    message_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[ReportReason] = mapped_column(
        Enum(ReportReason, name="report_reason", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<Report reporter={self.reporter_id} reported={self.reported_user_id} reason={self.reason}>"
