import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import month_label
from app.models.user import User
from app.repositories.dashboard_repository import DashboardRepository
from app.schemas.common import Page
from app.schemas.dashboard import (
    FavoriteTerrain,
    HistoryItem,
    MonthlyStats,
    PlayerDashboard,
    PlayerStats,
    UpcomingReservation,
)


class DashboardService:
    def __init__(self, db: AsyncSession):
        self.repo = DashboardRepository(db)

    async def get_full_dashboard(self, player: User) -> PlayerDashboard:
        """
        Construit le tableau de bord complet en 4 requêtes SQL séquentielles.
        Chaque requête est optimisée (agrégation ou JOIN) — aucun N+1.
        """
        upcoming_rows = await self.repo.get_upcoming(player.id, limit=5)
        stats_row = await self.repo.get_aggregate_stats(player.id)
        fav_row = await self.repo.get_favorite_terrain(player.id)
        monthly_rows = await self.repo.get_monthly_stats(player.id, months=6)

        return PlayerDashboard(
            upcoming_reservations=_build_upcoming(upcoming_rows),
            stats=PlayerStats(
                total_reservations=stats_row.total_reservations or 0,
                completed_reservations=int(stats_row.completed_reservations or 0),
                cancelled_reservations=int(stats_row.cancelled_reservations or 0),
                active_reservations=int(stats_row.active_reservations or 0),
                total_hours_played=round((stats_row.total_minutes or 0.0) / 60, 2),
                total_spent=round(stats_row.total_spent or 0.0, 2),
            ),
            favorite_terrain=(
                FavoriteTerrain(
                    terrain_id=fav_row.terrain_id,
                    terrain_name=fav_row.terrain_name,
                    terrain_city=fav_row.terrain_city,
                    booking_count=fav_row.booking_count,
                )
                if fav_row
                else None
            ),
            monthly_stats=_build_monthly(monthly_rows),
        )

    async def get_upcoming(
        self, player: User, limit: int = 10
    ) -> list[UpcomingReservation]:
        rows = await self.repo.get_upcoming(player.id, limit=limit)
        return _build_upcoming(rows)

    async def get_history(
        self, player: User, skip: int, limit: int
    ) -> Page[HistoryItem]:
        rows, total = await self.repo.get_history_page(player.id, skip, limit)
        items = [
            HistoryItem(
                id=r.id,
                terrain_id=r.terrain_id,
                terrain_name=r.terrain_name,
                terrain_city=r.terrain_city,
                start_datetime=r.start_datetime,
                end_datetime=r.end_datetime,
                duration_minutes=int(
                    (r.end_datetime - r.start_datetime).total_seconds() / 60
                ),
                total_price=r.total_price,
                status=r.status,
            )
            for r in rows
        ]
        return Page.build(items=items, total=total, skip=skip, limit=limit)


# ── Helpers module-level (pas de self, faciles à tester) ───────────────────────

def _build_upcoming(rows) -> list[UpcomingReservation]:
    return [
        UpcomingReservation(
            id=r.id,
            terrain_id=r.terrain_id,
            terrain_name=r.terrain_name,
            terrain_city=r.terrain_city,
            start_datetime=r.start_datetime,
            end_datetime=r.end_datetime,
            duration_minutes=int(
                (r.end_datetime - r.start_datetime).total_seconds() / 60
            ),
            total_price=r.total_price,
            status=r.status,
        )
        for r in rows
    ]


def _build_monthly(rows) -> list[MonthlyStats]:
    result = []
    for r in rows:
        year = int(r.year)
        month = int(r.month)
        result.append(
            MonthlyStats(
                year=year,
                month=month,
                month_label=month_label(year, month),
                reservations_count=r.reservations_count,
                total_hours=round((r.total_minutes or 0.0) / 60, 2),
                total_spent=round(r.total_spent or 0.0, 2),
            )
        )
    return result
