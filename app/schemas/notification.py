import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.notification import NotificationType
from app.schemas.common import Page


class NotificationResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    data: dict | None
    is_read: bool
    read_at: datetime | None
    reservation_id: uuid.UUID | None
    payment_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UnreadCount(BaseModel):
    count: int


class BulkReadResult(BaseModel):
    updated: int


class FcmTokenRegister(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class ReminderResult(BaseModel):
    sent: int
    message: str
