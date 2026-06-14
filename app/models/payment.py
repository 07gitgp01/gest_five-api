import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy import Enum as SAEnum, Numeric, Uuid
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class PaymentMethod(str, PyEnum):
    ORANGE_MONEY = "orange_money"
    MOOV_MONEY = "moov_money"
    CARD = "card"


class PaymentStatus(str, PyEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class Payment(Base, TimestampMixin):
    """
    Paiement lié à une réservation.

    - transaction_reference : référence interne GestFive (GF-OM-XXXX)
    - provider_reference    : identifiant retourné par le fournisseur
    - provider_data         : payload brut du webhook (pour audit)
    """

    __tablename__ = "payments"

    __table_args__ = (
        # Vérification d'un paiement actif par réservation
        Index("ix_payments_reservation_status", "reservation_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reservations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Numeric(12, 2) : précision DECIMAL en PostgreSQL pour les montants XOF
    amount: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="XOF")
    payment_method: Mapped[PaymentMethod] = mapped_column(
        SAEnum(PaymentMethod), nullable=False
    )
    # Référence unique générée par GestFive — transmise au fournisseur
    transaction_reference: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    # Référence retournée par le fournisseur dans le webhook
    provider_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus),
        default=PaymentStatus.PENDING,
        nullable=False,
        index=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Payload brut du webhook stocké pour traçabilité / support
    provider_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Notes internes ou raison d'un refus
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    reservation: Mapped["Reservation"] = relationship(back_populates="payments")
