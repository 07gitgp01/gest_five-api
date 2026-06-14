import uuid
from pydantic import BaseModel


# ── Stats générales ───────────────────────────────────────────────────────────

class OwnerStats(BaseModel):
    # Aujourd'hui (réservations non-annulées avec start_datetime = aujourd'hui UTC)
    today_revenue: float
    today_reservations: int
    # Mois en cours
    month_revenue: float
    month_reservations: int
    # Tout temps
    total_revenue: float
    total_reservations: int
    # Terrains
    total_terrains: int
    active_terrains: int


# ── Taux d'occupation ─────────────────────────────────────────────────────────

class TerrainOccupancy(BaseModel):
    terrain_id: uuid.UUID
    terrain_name: str
    terrain_city: str
    booked_hours: float          # heures réservées (non-annulées) ce mois
    capacity_hours: float        # heures d'exploitation totales ce mois
    occupancy_rate: float        # pourcentage 0–100, arrondi à 1 décimale


# ── Heures de pointe ──────────────────────────────────────────────────────────

class PeakHour(BaseModel):
    hour: int                    # 0–23
    hour_label: str              # ex. "10h00 - 11h00"
    reservations_count: int
    percentage: float            # part sur le total non-annulé analysé


# ── Revenus ───────────────────────────────────────────────────────────────────

class DailyRevenue(BaseModel):
    date: str                    # "YYYY-MM-DD"
    revenue: float
    reservations_count: int


class MonthlyRevenue(BaseModel):
    year: int
    month: int
    month_label: str             # "Juin 2026"
    revenue: float
    reservations_count: int


class RevenueSummary(BaseModel):
    daily_last_7_days: list[DailyRevenue]
    monthly_last_6_months: list[MonthlyRevenue]


# ── Dashboard complet ─────────────────────────────────────────────────────────

class OwnerDashboard(BaseModel):
    """
    Tableau de bord propriétaire — construit en 6 requêtes SQL max.
    Pas de N+1 : occupation via LEFT OUTER JOIN avec filtres dans ON,
    heures de pointe via GROUP BY EXTRACT(hour), revenus via GROUP BY date/mois.
    """
    stats: OwnerStats
    terrain_occupancy: list[TerrainOccupancy]
    peak_hours: list[PeakHour]
    daily_revenue: list[DailyRevenue]
    monthly_revenue: list[MonthlyRevenue]
