import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

from app.models.user import UserRole

# Format E.164 : + suivi de 8 à 15 chiffres
_E164_RE = re.compile(r"^\+\d{8,15}$")


class UserRegister(BaseModel):
    firstname: str
    lastname: str
    phone: str
    email: EmailStr | None = None
    password: str
    # Seuls CLIENT et OWNER sont auto-attribuables à l'inscription.
    # Le rôle ADMIN est réservé à la promotion via PATCH /admin/users/{id}/role.
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
        """Normalise vers E.164 (+22670123456) et valide le format."""
        # Supprime espaces, tirets, points
        normalized = re.sub(r"[\s\-\.]", "", v.strip())
        # Ajoute le + s'il est absent
        if not normalized.startswith("+"):
            normalized = "+" + normalized
        if not _E164_RE.match(normalized):
            raise ValueError(
                "Numéro invalide — format attendu : +22670123456 (E.164, 8 à 15 chiffres)"
            )
        return normalized  # retourne la forme normalisée

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Au moins 8 caractères requis")
        if not any(c.isdigit() for c in v):
            raise ValueError("Au moins un chiffre requis")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: UserRole) -> UserRole:
        if v == UserRole.ADMIN:
            raise ValueError(
                "Le rôle ADMIN ne peut pas être auto-attribué à l'inscription. "
                "Utilisez PATCH /admin/users/{id}/role pour promouvoir un compte."
            )
        return v


class UserLogin(BaseModel):
    identifier: str  # email ou numéro de téléphone
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
