import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.terrain import TerrainStatus
from app.models.user import UserRole
from app.schemas.common import Page


# ── Gestion utilisateurs ──────────────────────────────────────────────────────

class AdminUserResponse(BaseModel):
    id: uuid.UUID
    firstname: str
    lastname: str
    phone: str
    email: str | None
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserRoleUpdate(BaseModel):
    role: UserRole


# ── Gestion terrains ──────────────────────────────────────────────────────────

class AdminTerrainResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    owner_name: str           # "{firstname} {lastname}" issu d'un JOIN
    name: str
    address: str
    city: str
    status: TerrainStatus
    price_per_hour: float
    average_rating: float
    created_at: datetime
    updated_at: datetime


class TerrainSuspendRequest(BaseModel):
    reason: str = ""


# ── Statistiques plateforme ───────────────────────────────────────────────────

class UserStats(BaseModel):
    total: int
    active: int
    inactive: int
    clients: int
    owners: int
    admins: int
    new_this_month: int


class TerrainStats(BaseModel):
    total: int
    active: int
    inactive: int
    maintenance: int


class ReservationStats(BaseModel):
    total: int
    pending: int
    confirmed: int
    completed: int
    cancelled: int


class RevenueStats(BaseModel):
    total_revenue: float      # toutes réservations non-annulées
    month_revenue: float      # mois en cours
    total_successful_payments: int


class PlatformStats(BaseModel):
    users: UserStats
    terrains: TerrainStats
    reservations: ReservationStats
    revenue: RevenueStats


# ── Croissance mensuelle ──────────────────────────────────────────────────────

class MonthlyGrowth(BaseModel):
    year: int
    month: int
    month_label: str
    new_users: int
    new_terrains: int
    reservations: int
    revenue: float


class GrowthReport(BaseModel):
    data: list[MonthlyGrowth]
    users_growth_pct: float | None    # % vs mois précédent (None si données insuffisantes)
    revenue_growth_pct: float | None
