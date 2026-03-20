from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    RETRYING = "retrying"
    DELIVERED = "delivered"
    FAILED = "failed"


class NotificationDelivery(TimestampMixin, Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index("ix_notification_deliveries_status_next_attempt_at", "status", "next_attempt_at"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        CheckConstraint(
            "response_status IS NULL OR (response_status >= 100 AND response_status <= 599)",
            name="response_status_http_bounds",
        ),
        CheckConstraint(
            "((status = 'PENDING') AND attempt_count = 0) "
            "OR ((status IN ('RETRYING', 'DELIVERED', 'FAILED')) AND attempt_count > 0)",
            name="attempt_count_matches_status",
        ),
        CheckConstraint(
            "((status = 'DELIVERED') AND sent_at IS NOT NULL) "
            "OR ((status <> 'DELIVERED') AND sent_at IS NULL)",
            name="sent_at_matches_status",
        ),
        CheckConstraint(
            "(status <> 'DELIVERED') "
            "OR (response_status IS NOT NULL AND response_status >= 200 AND response_status <= 299)",
            name="delivered_response_status_bounds",
        ),
        CheckConstraint(
            "(status <> 'DELIVERED') OR last_error IS NULL",
            name="delivered_last_error_cleared",
        ),
        CheckConstraint(
            "(status <> 'PENDING') OR (last_error IS NULL AND response_status IS NULL)",
            name="pending_has_no_delivery_result",
        ),
        CheckConstraint(
            "(status NOT IN ('RETRYING', 'FAILED')) OR last_error IS NOT NULL",
            name="failed_or_retrying_requires_error",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger_id: Mapped[int] = mapped_column(ForeignKey("alert_triggers.id", ondelete="CASCADE"), nullable=False, unique=True)
    target_url: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, native_enum=False),
        default=DeliveryStatus.PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    trigger = relationship("AlertTrigger", back_populates="delivery")
