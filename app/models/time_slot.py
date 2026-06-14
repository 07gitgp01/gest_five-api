import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy import Enum as SAEnum, Numeric, Uuid
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class SlotType(str, PyEnum):
    REGULAR = "regular"
    PEAK = "peak"       # heures de pointe — tarif majoré (variable pricing hook)
    OFF_PEAK = "off_peak"  # heures creuses — tarif réduit


class SlotStatus(str, PyEnum):
    AVAILABLE = "available"
    BOOKED = "booked"
    BLOCKED = "blocked"     # bloqué manuellement par le propriétaire
    CANCELLED = "cancelled"


class TimeSlot(Base, TimestampMixin):
    """
    Créneau horodaté défini par un propriétaire.

    Extensibilité prévue :
    - recurrence_rule : règle iCalendar-like pour créneaux récurrents
      ex: {"frequency": "weekly", "days_of_week": ["monday", "wednesday"],
           "until": "2026-12-31", "exceptions": ["2025-12-25"]}
    - price_override : surcharge de prix pour tarification variable par heure
    - slot_type : PEAK / OFF_PEAK pour les offres horaires différenciées
    """

    __tablename__ = "time_slots"

    __table_args__ = (
        # Requête la plus fréquente : créneaux AVAILABLE d'un terrain dans une plage
        Index("ix_slots_terrain_status_start", "terrain_id", "status", "start_datetime"),
        # Détection de conflits de chevauchement
        Index("ix_slots_terrain_dates", "terrain_id", "start_datetime", "end_datetime"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    terrain_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("terrains.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    slot_type: Mapped[SlotType] = mapped_column(
        SAEnum(SlotType), default=SlotType.REGULAR, nullable=False
    )
    status: Mapped[SlotStatus] = mapped_column(
        SAEnum(SlotStatus), default=SlotStatus.AVAILABLE, nullable=False
    )
    # None → prix calculé depuis terrain.price_per_hour × durée
    price_override: Mapped[float | None] = mapped_column(
        Numeric(12, 2, asdecimal=False), nullable=True
    )
    # Règle de récurrence (extensibilité future pour abonnements hebdomadaires)
    recurrence_rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    terrain: Mapped["Terrain"] = relationship(back_populates="time_slots")
    reservation: Mapped["Reservation | None"] = relationship(
        back_populates="time_slot", uselist=False
    )
