import uuid
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from app.models.time_slot import SlotStatus, SlotType


# ── Entrée ─────────────────────────────────────────────────────────────────────

class TimeSlotCreate(BaseModel):
    start_datetime: datetime
    end_datetime: datetime
    slot_type: SlotType = SlotType.REGULAR
    price_override: float | None = Field(default=None, ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_slot(self) -> "TimeSlotCreate":
        if self.end_datetime <= self.start_datetime:
            raise ValueError("end_datetime doit être après start_datetime")
        duration_min = (self.end_datetime - self.start_datetime).total_seconds() / 60
        if duration_min < 30:
            raise ValueError("Durée minimale : 30 minutes")
        if duration_min > 480:
            raise ValueError("Durée maximale : 8 heures")
        if self.start_datetime.date() != self.end_datetime.date():
            raise ValueError("Un créneau ne peut pas dépasser minuit")
        if self.start_datetime < datetime.now(timezone.utc):
            raise ValueError("Le créneau ne peut pas être dans le passé")
        return self


class TimeSlotUpdate(BaseModel):
    status: SlotStatus | None = None
    price_override: float | None = Field(default=None, ge=0)
    notes: str | None = None


class SlotGenerateRequest(BaseModel):
    """Génère des créneaux en masse à partir des horaires d'ouverture du terrain."""
    date_from: date
    date_to: date
    duration_minutes: int = Field(default=60, description="30 | 60 | 90 | 120")
    slot_type: SlotType = SlotType.REGULAR
    price_override: float | None = Field(default=None, ge=0)

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        if v not in (30, 60, 90, 120):
            raise ValueError("duration_minutes doit être 30, 60, 90 ou 120")
        return v

    @model_validator(mode="after")
    def validate_range(self) -> "SlotGenerateRequest":
        if self.date_to < self.date_from:
            raise ValueError("date_to doit être >= date_from")
        if (self.date_to - self.date_from).days > 90:
            raise ValueError("Plage maximale : 90 jours")
        return self


# ── Sortie ─────────────────────────────────────────────────────────────────────

class TimeSlotResponse(BaseModel):
    id: uuid.UUID
    terrain_id: uuid.UUID
    start_datetime: datetime
    end_datetime: datetime
    slot_type: SlotType
    status: SlotStatus
    price_override: float | None
    notes: str | None

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def duration_minutes(self) -> int:
        return int((self.end_datetime - self.start_datetime).total_seconds() / 60)


class SlotGenerateSummary(BaseModel):
    terrain_id: uuid.UUID
    date_from: date
    date_to: date
    created_count: int
    skipped_count: int


# ── Disponibilité ──────────────────────────────────────────────────────────────

class ConflictInfo(BaseModel):
    slot_id: uuid.UUID
    start_datetime: datetime
    end_datetime: datetime
    status: SlotStatus

    model_config = {"from_attributes": True}


class AvailabilityResult(BaseModel):
    available: bool
    terrain_id: uuid.UUID
    start_datetime: datetime
    end_datetime: datetime
    reason: str | None = None
    conflicts: list[ConflictInfo] = []
