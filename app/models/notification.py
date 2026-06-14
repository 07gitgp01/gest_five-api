import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin


class NotificationType(str, PyEnum):
    RESERVATION_CONFIRMED = "reservation_confirmed"
    PAYMENT_SUCCESS = "payment_success"
    CANCELLATION = "cancellation"
    MATCH_REMINDER = "match_reminder"
    GENERAL = "general"


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    __table_args__ = (
        # Liste notifications d'un utilisateur avec filtre lu/non-lu
        Index("ix_notif_user_read_created", "user_id", "is_read", "created_at"),
        # Idempotence des rappels de match (reminder_already_sent)
        Index("ix_notif_reservation_type", "reservation_id", "type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Payload FCM libre (clés envoyées en data dans le message Firebase)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Liens optionnels vers les entités concernées (SET NULL si supprimées)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reservations.id", ondelete="SET NULL"),
        nullable=True,
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
    )

    user: Mapped["User"] = relationship(back_populates="notifications")
