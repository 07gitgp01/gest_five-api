import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, extract, func, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_expressions import duration_minutes_expr
from app.models.reservation import Reservation, ReservationStatus
from app.models.terrain import Terrain


class DashboardRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._duration_expr = duration_minutes_expr(
            Reservation.start_datetime, Reservation.end_datetime
        )

    async def get_upcoming(
        self, player_id: uuid.UUID, limit: int = 5
    ) -> list[Row]:
        """Prochaines réservations actives — JOIN terrain en une passe (pas de N+1)."""
        query = (
            select(
                Reservation.id,
                Reservation.terrain_id,
                Reservation.start_datetime,
                Reservation.end_datetime,
                Reservation.total_price,
                Reservation.status,
                Terrain.name.label("terrain_name"),
                Terrain.city.label("terrain_city"),
            )
            .join(Terrain, Reservation.terrain_id == Terrain.id)
            .where(
                and_(
                    Reservation.player_id == player_id,
                    Reservation.start_datetime >= func.now(),
                    Reservation.status.in_(
                        [ReservationStatus.PENDING, ReservationStatus.CONFIRMED]
                    ),
                )
            )
            .order_by(Reservation.start_datetime.asc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.all())

    async def get_history_page(
        self,
        player_id: uuid.UUID,
        skip: int,
        limit: int,
    ) -> tuple[list[Row], int]:
        """Historique paginé (passé OU annulé/terminé) — JOIN terrain."""
        is_history = or_(
            Reservation.start_datetime < func.now(),
            Reservation.status.in_(
                [ReservationStatus.CANCELLED, ReservationStatus.COMPLETED]
            ),
        )
        base_where = and_(Reservation.player_id == player_id, is_history)

        total = (
            await self.db.execute(
                select(func.count(Reservation.id)).where(base_where)
            )
        ).scalar_one()

        rows_q = (
            select(
                Reservation.id,
                Reservation.terrain_id,
                Reservation.start_datetime,
                Reservation.end_datetime,
                Reservation.total_price,
                Reservation.status,
                Terrain.name.label("terrain_name"),
                Terrain.city.label("terrain_city"),
            )
            .join(Terrain, Reservation.terrain_id == Terrain.id)
            .where(base_where)
            .order_by(Reservation.start_datetime.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = list((await self.db.execute(rows_q)).all())
        return rows, total

    async def get_aggregate_stats(self, player_id: uuid.UUID) -> Row:
        """
        Une seule requête SQL pour toutes les stats globales :
        totaux, statuts, heures jouées (COMPLETED seulement), montant dépensé.
        """
        completed_cond = Reservation.status == ReservationStatus.COMPLETED
        cancelled_cond = Reservation.status == ReservationStatus.CANCELLED
        active_cond = Reservation.status.in_(
            [ReservationStatus.PENDING, ReservationStatus.CONFIRMED]
        )

        query = select(
            func.count(Reservation.id).label("total_reservations"),
            func.sum(case((completed_cond, 1), else_=0)).label(
                "completed_reservations"
            ),
            func.sum(case((cancelled_cond, 1), else_=0)).label(
                "cancelled_reservations"
            ),
            func.sum(case((active_cond, 1), else_=0)).label("active_reservations"),
            func.coalesce(
                func.sum(
                    case((completed_cond, self._duration_expr), else_=None)
                ),
                0.0,
            ).label("total_minutes"),
            func.coalesce(func.sum(Reservation.total_price), 0.0).label(
                "total_spent"
            ),
        ).where(Reservation.player_id == player_id)

        return (await self.db.execute(query)).one()

    async def get_favorite_terrain(self, player_id: uuid.UUID) -> Row | None:
        """Terrain avec le plus de réservations non-annulées (GROUP BY + COUNT)."""
        query = (
            select(
                Terrain.id.label("terrain_id"),
                Terrain.name.label("terrain_name"),
                Terrain.city.label("terrain_city"),
                func.count(Reservation.id).label("booking_count"),
            )
            .join(Terrain, Reservation.terrain_id == Terrain.id)
            .where(
                and_(
                    Reservation.player_id == player_id,
                    Reservation.status != ReservationStatus.CANCELLED,
                )
            )
            .group_by(Terrain.id, Terrain.name, Terrain.city)
            .order_by(func.count(Reservation.id).desc())
            .limit(1)
        )
        return (await self.db.execute(query)).one_or_none()

    async def get_monthly_stats(
        self, player_id: uuid.UUID, months: int = 6
    ) -> list[Row]:
        """Statistiques mensuelles hors annulations — GROUP BY année/mois."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)

        year_expr = extract("year", Reservation.start_datetime)
        month_expr = extract("month", Reservation.start_datetime)

        query = (
            select(
                year_expr.label("year"),
                month_expr.label("month"),
                func.count(Reservation.id).label("reservations_count"),
                func.coalesce(
                    func.sum(self._duration_expr), 0.0
                ).label("total_minutes"),
                func.coalesce(
                    func.sum(Reservation.total_price), 0.0
                ).label("total_spent"),
            )
            .where(
                and_(
                    Reservation.player_id == player_id,
                    Reservation.start_datetime >= cutoff,
                    Reservation.status != ReservationStatus.CANCELLED,
                )
            )
            .group_by(year_expr, month_expr)
            .order_by(year_expr.desc(), month_expr.desc())
        )
        result = await self.db.execute(query)
        return list(result.all())
