import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

from app.models.user import UserRole


class UserRegister(BaseModel):
    firstname: str
    lastname: str
    phone: str
    email: EmailStr | None = None
    password: str
    role: UserRole = UserRole.CLIENT

    @field_validator("firstname", "lastname")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Doit contenir au moins 2 caractères")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = v.replace("+", "").replace(" ", "").replace("-", "")
        if not digits.isdigit() or len(digits) < 8:
            raise ValueError("Numéro de téléphone invalide")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Au moins 8 caractères requis")
        if not any(c.isdigit() for c in v):
            raise ValueError("Au moins un chiffre requis")
        return v


class UserLogin(BaseModel):
    phone: str
    password: str


class UserResponse(BaseModel):
    id: uuid.UUID
    firstname: str
    lastname: str
    phone: str
    email: str | None
    avatar: str | None
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    firstname: str | None = None
    lastname: str | None = None
    avatar: str | None = None

    @field_validator("firstname", "lastname")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) < 2:
                raise ValueError("Doit contenir au moins 2 caractères")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Au moins 8 caractères requis")
        if not any(c.isdigit() for c in v):
            raise ValueError("Au moins un chiffre requis")
        return v
