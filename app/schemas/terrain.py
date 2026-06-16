import uuid
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.terrain import TerrainStatus


# ── Horaires ────────────────────────────────────────────────────────────────────

class DaySchedule(BaseModel):
    open: str = "08:00"
    close: str = "22:00"
    is_closed: bool = False

    @field_validator("open", "close")
    @classmethod
    def validate_time(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ValueError("Format attendu : HH:MM")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Heure invalide")
        return v


class OpeningHours(BaseModel):
    monday: DaySchedule = Field(default_factory=DaySchedule)
    tuesday: DaySchedule = Field(default_factory=DaySchedule)
    wednesday: DaySchedule = Field(default_factory=DaySchedule)
    thursday: DaySchedule = Field(default_factory=DaySchedule)
    friday: DaySchedule = Field(default_factory=DaySchedule)
    saturday: DaySchedule = Field(default_factory=DaySchedule)
    sunday: DaySchedule = Field(default_factory=lambda: DaySchedule(is_closed=True))


# ── Paramètres de recherche (utilisés par le repo et le service) ───────────────

@dataclass
class TerrainSearchParams:
    city: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    has_parking: bool | None = None
    has_lighting: bool | None = None
    has_changing_room: bool | None = None
    has_shower: bool | None = None


# ── Schemas entrée ─────────────────────────────────────────────────────────────

class TerrainCreate(BaseModel):
    name: str
    description: str | None = None
    address: str
    city: str
    latitude: float | None = None
    longitude: float | None = None
    photos: list[str] = Field(default_factory=list)
    opening_hours: OpeningHours = Field(default_factory=OpeningHours)
    price_per_hour: float
    capacity: int = Field(default=10, ge=2, le=30)
    has_parking: bool = False
    has_changing_room: bool = False
    has_shower: bool = False
    has_lighting: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Le nom doit contenir au moins 3 caractères")
        return v

    @field_validator("price_per_hour")
    @classmethod
    def validate_price(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Le prix doit être positif")
        return v


class TerrainUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    address: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    photos: list[str] | None = None
    opening_hours: OpeningHours | None = None
    price_per_hour: float | None = None
    capacity: int | None = Field(default=None, ge=2, le=30)
    has_parking: bool | None = None
    has_changing_room: bool | None = None
    has_shower: bool | None = None
    has_lighting: bool | None = None
    status: TerrainStatus | None = None


# ── Schemas sortie ─────────────────────────────────────────────────────────────

class TerrainSummary(BaseModel):
    """Vue allégée pour les listes publiques."""
    id: uuid.UUID
    name: str
    city: str
    address: str
    latitude: float | None
    longitude: float | None
    price_per_hour: float
    average_rating: float
    capacity: int
    has_parking: bool
    has_lighting: bool
    has_shower: bool
    has_changing_room: bool
    photos: list
    status: TerrainStatus

    model_config = {"from_attributes": True}


class TerrainResponse(BaseModel):
    """Vue complète d'un terrain."""
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    address: str
    city: str
    latitude: float | None
    longitude: float | None
    photos: list
    opening_hours: dict
    price_per_hour: float
    capacity: int
    has_parking: bool
    has_changing_room: bool
    has_shower: bool
    has_lighting: bool
    average_rating: float
    status: TerrainStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
