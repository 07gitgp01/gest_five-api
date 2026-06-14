import uuid
from datetime import datetime

from pydantic import BaseModel, computed_field, model_validator

from app.models.reservation import ReservationStatus


class ReservationCreate(BaseModel):
    """
    Deux modes :
    - Slot-based : fournir time_slot_id uniquement
    - Direct     : fournir terrain_id + start_datetime + end_datetime
    """

    time_slot_id: uuid.UUID | None = None
    terrain_id: uuid.UUID | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_booking_mode(self) -> "ReservationCreate":
        if self.time_slot_id:
            return self
        if not all([self.terrain_id, self.start_datetime, self.end_datetime]):
            raise ValueError(
                "Fournir soit time_slot_id, soit (terrain_id + start_datetime + end_datetime)"
            )
        if self.end_datetime <= self.start_datetime:
            raise ValueError("end_datetime doit être après start_datetime")
        return self


class ReservationUpdate(BaseModel):
    """Utilisé par le propriétaire pour confirmer ou marquer comme terminée."""

    status: ReservationStatus | None = None
    notes: str | None = None


class ReservationResponse(BaseModel):
    id: uuid.UUID
    terrain_id: uuid.UUID
    player_id: uuid.UUID
    time_slot_id: uuid.UUID | None
    start_datetime: datetime
    end_datetime: datetime
    total_price: float
    status: ReservationStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def duration_minutes(self) -> int:
        return int((self.end_datetime - self.start_datetime).total_seconds() / 60)
