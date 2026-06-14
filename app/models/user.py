import uuid
from enum import Enum as PyEnum

from sqlalchemy import Boolean, String
from sqlalchemy import Enum as SAEnum, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class UserRole(str, PyEnum):
    CLIENT = "client"
    OWNER = "owner"
    ADMIN = "admin"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    firstname: Mapped[str] = mapped_column(String(100), nullable=False)
    lastname: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    # Argon2 hashes font ~95-150 chars — String(500) pour avoir de la marge
    hashed_password: Mapped[str] = mapped_column(String(500), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole), default=UserRole.CLIENT, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Token FCM pour les notifications push (mis à jour par l'app mobile)
    fcm_token: Mapped[str | None] = mapped_column(String(512), nullable=True)

    terrains: Mapped[list["Terrain"]] = relationship(back_populates="owner", lazy="select")
    reservations: Mapped[list["Reservation"]] = relationship(back_populates="player", lazy="select")
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user", lazy="select", cascade="all, delete-orphan"
    )
