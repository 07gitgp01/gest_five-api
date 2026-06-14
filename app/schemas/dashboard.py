import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.reservation import ReservationStatus


# ── Prochaines réservations ────────────────────────────────────────────────────

class UpcomingReservation(BaseModel):
    id: uuid.UUID
    terrain_id: uuid.UUID
    terrain_name: str
    terrain_city: str
    start_datetime: datetime
    end_datetime: datetime
    duration_minutes: int
    total_price: float
    status: ReservationStatus


# ── Historique ─────────────────────────────────────────────────────────────────

class HistoryItem(BaseModel):
    id: uuid.UUID
    terrain_id: uuid.UUID
    terrain_name: str
    terrain_city: str
    start_datetime: datetime
    end_datetime: datetime
    duration_minutes: int
    total_price: float
    status: ReservationStatus


# ── Statistiques globales ──────────────────────────────────────────────────────

class PlayerStats(BaseModel):
    total_reservations: int
    completed_reservations: int
    cancelled_reservations: int
    active_reservations: int        # PENDING + CONFIRMED
    total_hours_played: float = Field(description="Heures sur réservations COMPLETED")
    total_spent: float              # Somme de tous les total_price


# ── Terrain préféré ───────────────────────────────────────────────────────────

class FavoriteTerrain(BaseModel):
    terrain_id: uuid.UUID
    terrain_name: str
    terrain_city: str
    booking_count: int


# ── Statistiques mensuelles ────────────────────────────────────────────────────

class MonthlyStats(BaseModel):
    year: int
    month: int
    month_label: str              # "Juin 2026"
    reservations_count: int
    total_hours: float
    total_spent: float


# ── Dashboard complet ─────────────────────────────────────────────────────────

class PlayerDashboard(BaseModel):
    """Vue synthétique du tableau de bord — construit en 4 requêtes SQL."""

    upcoming_reservations: list[UpcomingReservation]
    stats: PlayerStats
    favorite_terrain: FavoriteTerrain | None
    monthly_stats: list[MonthlyStats]
