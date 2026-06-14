import calendar
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.owner_dashboard_repository import OwnerDashboardRepository
from app.schemas.owner_dashboard import (
    DailyRevenue,
    MonthlyRevenue,
    OwnerDashboard,
    OwnerStats,
    PeakHour,
    RevenueSummary,
    TerrainOccupancy,
)

_FR_MONTHS = [
    "",
    "Janvier",
    "Février",
    "Mars",
    "Avril",
    "Mai",
    "Juin",
    "Juillet",
    "Août",
    "Septembre",
    "Octobre",
    "Novembre",
    "Décembre",
]

_DAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def _month_boundaries(now: datetime) -> tuple[datetime, datetime]:
    """Retourne (début_mois, début_mois_suivant) en UTC."""
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)
    return month_start, month_end


def _compute_capacity_hours(opening_hours: dict, year: int, month: int) -> float:
    """
    Calcule les heures d'exploitation d'un terrain sur un mois entier
    à partir du JSON opening_hours. Exemple de format :
    {"monday": {"open": "08:00", "close": "22:00", "is_closed": false}, ...}
    """
    first_weekday = date(year, month, 1).weekday()  # 0 = Monday
    days_in_month = calendar.monthrange(year, month)[1]
    total = 0.0
    for day_offset in range(days_in_month):
        weekday = (first_weekday + day_offset) % 7
        config = opening_hours.get(_DAY_NAMES[weekday], {})
        if config.get("is_closed", True):
            continue
        try:
            oh, om = map(int, config["open"].split(":"))
            ch, cm = map(int, config["close"].split(":"))
            total += (ch * 60 + cm - oh * 60 - om) / 60.0
        except (KeyError, ValueError, AttributeError):
            pass
    return round(total, 2)


class OwnerDashboardService:
    def __init__(self, db: AsyncSession):
        self.repo = OwnerDashboardRepository(db)

    async def get_full_dashboard(self, owner: User) -> OwnerDashboard:
        """
        6 requêtes SQL séquentielles, toutes agrégées — aucun N+1.
        La capacité des terrains est calculée en Python à partir du JSON
        opening_hours (logique trop complexe pour une seule requête cross-db).
        """
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        month_start, month_end = _month_boundaries(now)
        six_months_ago = now - timedelta(days=180)
        seven_days_ago = today_start - timedelta(days=7)
        three_months_ago = now - timedelta(days=90)

        terrain_row = await self.repo.get_terrain_counts(owner.id)
        revenue_row = await self.repo.get_revenue_stats(
            owner.id, today_start, today_end, month_start, month_end
        )
        occupancy_rows = await self.repo.get_terrain_occupancy_rows(
            owner.id, month_start, month_end
        )
        peak_rows = await self.repo.get_peak_hours(owner.id, three_months_ago, limit=10)
        daily_rows = await self.repo.get_daily_revenue(owner.id, seven_days_ago)
        monthly_rows = await self.repo.get_monthly_revenue(owner.id, six_months_ago)

        return OwnerDashboard(
            stats=_build_stats(terrain_row, revenue_row),
            terrain_occupancy=_build_occupancy(
                occupancy_rows, now.year, now.month
            ),
            peak_hours=_build_peak_hours(peak_rows),
            daily_revenue=_build_daily(daily_rows),
            monthly_revenue=_build_monthly(monthly_rows),
        )

    async def get_occupancy(self, owner: User) -> list[TerrainOccupancy]:
        now = datetime.now(timezone.utc)
        month_start, month_end = _month_boundaries(now)
        rows = await self.repo.get_terrain_occupancy_rows(
            owner.id, month_start, month_end
        )
        return _build_occupancy(rows, now.year, now.month)

    async def get_peak_hours_summary(
        self, owner: User, months: int = 3
    ) -> list[PeakHour]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
        rows = await self.repo.get_peak_hours(owner.id, cutoff, limit=24)
        return _build_peak_hours(rows)

    async def get_revenue_summary(self, owner: User) -> RevenueSummary:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_rows = await self.repo.get_daily_revenue(
            owner.id, today_start - timedelta(days=7)
        )
        monthly_rows = await self.repo.get_monthly_revenue(
            owner.id, now - timedelta(days=180)
        )
        return RevenueSummary(
            daily_last_7_days=_build_daily(daily_rows),
            monthly_last_6_months=_build_monthly(monthly_rows),
        )


# ── Helpers module-level ───────────────────────────────────────────────────────

def _build_stats(terrain_row, revenue_row) -> OwnerStats:
    return OwnerStats(
        today_revenue=round(float(revenue_row.today_revenue or 0), 2),
        today_reservations=int(revenue_row.today_reservations or 0),
        month_revenue=round(float(revenue_row.month_revenue or 0), 2),
        month_reservations=int(revenue_row.month_reservations or 0),
        total_revenue=round(float(revenue_row.total_revenue or 0), 2),
        total_reservations=int(revenue_row.total_reservations or 0),
        total_terrains=int(terrain_row.total_terrains or 0),
        active_terrains=int(terrain_row.active_terrains or 0),
    )


def _build_occupancy(rows, year: int, month: int) -> list[TerrainOccupancy]:
    result = []
    for row in rows:
        booked_hours = round((row.booked_minutes or 0.0) / 60, 2)
        capacity_hours = _compute_capacity_hours(
            row.opening_hours or {}, year, month
        )
        if capacity_hours > 0:
            rate = round((booked_hours / capacity_hours) * 100, 1)
        else:
            rate = 0.0
        result.append(
            TerrainOccupancy(
                terrain_id=row.terrain_id,
                terrain_name=row.terrain_name,
                terrain_city=row.terrain_city,
                booked_hours=booked_hours,
                capacity_hours=capacity_hours,
                occupancy_rate=rate,
            )
        )
    return result


def _build_peak_hours(rows) -> list[PeakHour]:
    total = sum(int(r.reservations_count) for r in rows)
    result = []
    for row in rows:
        hour = int(row.hour)
        count = int(row.reservations_count)
        result.append(
            PeakHour(
                hour=hour,
                hour_label=f"{hour:02d}h00 - {(hour + 1) % 24:02d}h00",
                reservations_count=count,
                percentage=round(count / total * 100, 1) if total > 0 else 0.0,
            )
        )
    return result


def _build_daily(rows) -> list[DailyRevenue]:
    return [
        DailyRevenue(
            date=str(row.day)[:10],  # gère date object (PG) et string (SQLite)
            revenue=round(float(row.revenue or 0), 2),
            reservations_count=int(row.reservations_count),
        )
        for row in rows
    ]


def _build_monthly(rows) -> list[MonthlyRevenue]:
    result = []
    for row in rows:
        year = int(row.year)
        month = int(row.month)
        result.append(
            MonthlyRevenue(
                year=year,
                month=month,
                month_label=f"{_FR_MONTHS[month]} {year}",
                revenue=round(float(row.revenue or 0), 2),
                reservations_count=int(row.reservations_count),
            )
        )
    return result
