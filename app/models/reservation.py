import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy import Enum as SAEnum, Numeric, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class ReservationStatus(str, PyEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class Reservation(Base, TimestampMixin):
    """
    Réservation d'un terrain par un joueur.

    Deux modes :
    - Slot-based : time_slot_id renseigné → prix via AvailabilityService.compute_effective_price
    - Direct     : time_slot_id NULL      → prix = price_per_hour × durée_heures
    """

    __tablename__ = "reservations"

    __table_args__ = (
        # Détection de conflits temporels (requête la plus critique)
        Index("ix_res_terrain_dates", "terrain_id", "start_datetime", "end_datetime"),
        # Liste paginée avec filtre statut — player dashboard
        Index("ix_res_player_status", "player_id", "status"),
        # Liste paginée avec filtre statut — terrain owner dashboard
        Index("ix_res_terrain_status", "terrain_id", "status"),
        # Rappels de match : CONFIRMED dans une fenêtre temporelle
        Index("ix_res_status_start", "status", "start_datetime"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    terrain_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("terrains.id", ondelete="CASCADE"),
        nullable=False,
    )
    player_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SET NULL à la suppression du créneau — la réservation reste accessible
    time_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("time_slots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Numeric(12, 2) évite les erreurs de précision IEEE 754 sur les montants XOF
    total_price: Mapped[float] = mapped_column(Numeric(12, 2, asdecimal=False), nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        SAEnum(ReservationStatus),
        default=ReservationStatus.PENDING,
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    terrain: Mapped["Terrain"] = relationship(back_populates="reservations")
    player: Mapped["User"] = relationship(back_populates="reservations")
    time_slot: Mapped["TimeSlot | None"] = relationship(
        back_populates="reservation", uselist=False
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="reservation", cascade="all, delete-orphan"
    )
