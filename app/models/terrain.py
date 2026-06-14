import uuid
from enum import Enum as PyEnum

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum, Uuid
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class TerrainStatus(str, PyEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"


class Terrain(Base, TimestampMixin):
    __tablename__ = "terrains"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Liste d'URLs stockée en JSON
    photos: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Horaires par jour {"monday": {"open": "08:00", "close": "22:00", "is_closed": false}, ...}
    opening_hours: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    price_per_hour: Mapped[float] = mapped_column(Float, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    has_parking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_changing_room: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_shower: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_lighting: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Mis à jour lors de l'ajout / suppression d'un avis
    average_rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[TerrainStatus] = mapped_column(
        SAEnum(TerrainStatus),
        default=TerrainStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    owner: Mapped["User"] = relationship(back_populates="terrains")
    reservations: Mapped[list["Reservation"]] = relationship(
        back_populates="terrain",
        lazy="select",
        cascade="all, delete-orphan",
    )
