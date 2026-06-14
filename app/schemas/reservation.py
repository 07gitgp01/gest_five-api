import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator

from app.models.reservation import ReservationStatus


class ReservationBase(BaseModel):
    terrain_id: uuid.UUID
    start_time: datetime
    end_time: datetime
    notes: str | None = None

    @model_validator(mode="after")
    def validate_times(self) -> "ReservationBase":
        if self.end_time <= self.start_time:
            raise ValueError("end_time doit être après start_time")
        return self


class ReservationCreate(ReservationBase):
    pass


class ReservationUpdate(BaseModel):
    status: ReservationStatus | None = None
    notes: str | None = None


class ReservationResponse(ReservationBase):
    id: int
    player_id: uuid.UUID
    total_price: float
    status: ReservationStatus
    created_at: datetime

    model_config = {"from_attributes": True}
