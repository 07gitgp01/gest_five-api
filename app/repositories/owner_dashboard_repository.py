import uuid
from datetime import datetime

from sqlalchemy import and_, case, extract, func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_expressions import duration_minutes_expr, hour_of_day_expr
from app.models.reservation import Reservation, ReservationStatus
from app.models.terrain import Terrain, TerrainStatus


class OwnerDashboardRepository:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._duration_expr = duration_minutes_expr(
            Reservation.start_datetime, Reservation.end_datetime
        )
        self._hour_expr = hour_of_day_expr(Reservation.start_datetime)

    # ── Compteurs terrains ─────────────────────────────────────────────────────

    async def get_terrain_counts(self, owner_id: uuid.UUID) -> Row:
        """Nombre total et actif de terrains — sans JOIN."""
        query = select(
            func.count(Terrain.id).label("total_terrains"),
            func.sum(
                case((Terrain.status == TerrainStatus.ACTIVE, 1), else_=0)
            ).label("active_terrains"),
        ).where(Terrain.owner_id == owner_id)
        return (await self.db.execute(query)).one()

    # ── Agrégation revenus ─────────────────────────────────────────────────────

    async def get_revenue_stats(
        self,
        owner_id: uuid.UUID,
        today_start: datetime,
        today_end: datetime,
        month_start: datetime,
        month_end: datetime,
    ) -> Row:
        """
        Revenus et compteurs de réservations en une passe SQL :
        aujourd'hui / mois en cours / tout temps.
        Filtre r.status != CANCELLED dans le JOIN (pas dans WHERE)
        pour conserver les terrains sans réservations.
        """
        not_cancelled = Reservation.status != ReservationStatus.CANCELLED
        today_cond = and_(
            Reservation.start_datetime >= today_start,
            Reservation.start_datetime < today_end,
        )
        month_cond = and_(
            Reservation.start_datetime >= month_start,
            Reservation.start_datetime < month_end,
        )

        query = (
            select(
                func.coalesce(func.count(Reservation.id), 0).label(
                    "total_reservations"
                ),
                func.coalesce(func.sum(Reservation.total_price), 0.0).label(
                    "total_revenue"
                ),
                func.coalesce(
                    func.sum(case((today_cond, 1), else_=None)), 0
                ).label("today_reservations"),
                func.coalesce(
                    func.sum(case((today_cond, Reservation.total_price), else_=None)),
                    0.0,
                ).label("today_revenue"),
                func.coalesce(
                    func.sum(case((month_cond, 1), else_=None)), 0
                ).label("month_reservations"),
                func.coalesce(
                    func.sum(case((month_cond, Reservation.total_price), else_=None)),
                    0.0,
                ).label("month_revenue"),
            )
            .select_from(Reservation)
            .join(Terrain, Reservation.terrain_id == Terrain.id)
            .where(and_(Terrain.owner_id == owner_id, not_cancelled))
        )
        return (await self.db.execute(query)).one()

    # ── Occupation par terrain ─────────────────────────────────────────────────

    async def get_terrain_occupancy_rows(
        self,
        owner_id: uuid.UUID,
        month_start: datetime,
        month_end: datetime,
    ) -> list[Row]:
        """
        Heures réservées ce mois par terrain.
        LEFT OUTER JOIN avec filtres réservation dans la clause ON (pas WHERE),
        ce qui préserve les terrains sans réservation ce mois (booked_minutes=0).
        """
        res_filter = and_(
            Reservation.terrain_id == Terrain.id,
            Reservation.status != ReservationStatus.CANCELLED,
            Reservation.start_datetime >= month_start,
            Reservation.start_datetime < month_end,
        )
        query = (
            select(
                Terrain.id.label("terrain_id"),
                Terrain.name.label("terrain_name"),
                Terrain.city.label("terrain_city"),
                Terrain.opening_hours.label("opening_hours"),
                func.coalesce(func.sum(self._duration_expr), 0.0).label(
                    "booked_minutes"
                ),
            )
            .select_from(Terrain)
            .outerjoin(Reservation, res_filter)
            .where(Terrain.owner_id == owner_id)
            .group_by(
                Terrain.id, Terrain.name, Terrain.city, Terrain.opening_hours
            )
            .order_by(Terrain.name)
        )
        return list((await self.db.execute(query)).all())

    # ── Heures de pointe ───────────────────────────────────────────────────────

    async def get_peak_hours(
        self,
        owner_id: uuid.UUID,
        cutoff: datetime,
        limit: int = 10,
    ) -> list[Row]:
        """Heure de début la plus fréquente — GROUP BY heure entière."""
        query = (
            select(
                self._hour_expr.label("hour"),
                func.count(Reservation.id).label("reservations_count"),
            )
            .select_from(Reservation)
            .join(Terrain, Reservation.terrain_id == Terrain.id)
            .where(
                and_(
                    Terrain.owner_id == owner_id,
                    Reservation.status != ReservationStatus.CANCELLED,
                    Reservation.start_datetime >= cutoff,
                )
            )
            .group_by(self._hour_expr)
            .order_by(func.count(Reservation.id).desc())
            .limit(limit)
        )
        return list((await self.db.execute(query)).all())

    # ── Revenus journaliers ────────────────────────────────────────────────────

    async def get_daily_revenue(
        self, owner_id: uuid.UUID, from_date: datetime
    ) -> list[Row]:
        """Revenus groupés par jour — derniers 7 jours."""
        day_expr = func.date(Reservation.start_datetime)
        query = (
            select(
                day_expr.label("day"),
                func.coalesce(func.sum(Reservation.total_price), 0.0).label(
                    "revenue"
                ),
                func.count(Reservation.id).label("reservations_count"),
            )
            .select_from(Reservation)
            .join(Terrain, Reservation.terrain_id == Terrain.id)
            .where(
                and_(
                    Terrain.owner_id == owner_id,
                    Reservation.status != ReservationStatus.CANCELLED,
                    Reservation.start_datetime >= from_date,
                )
            )
            .group_by(day_expr)
            .order_by(day_expr.asc())
        )
        return list((await self.db.execute(query)).all())

    # ── Revenus mensuels ───────────────────────────────────────────────────────

    async def get_monthly_revenue(
        self, owner_id: uuid.UUID, cutoff: datetime
    ) -> list[Row]:
        """Revenus groupés par mois — 6 derniers mois hors annulations."""
        year_expr = extract("year", Reservation.start_datetime)
        month_expr = extract("month", Reservation.start_datetime)
        query = (
            select(
                year_expr.label("year"),
                month_expr.label("month"),
                func.coalesce(func.sum(Reservation.total_price), 0.0).label(
                    "revenue"
                ),
                func.count(Reservation.id).label("reservations_count"),
            )
            .select_from(Reservation)
            .join(Terrain, Reservation.terrain_id == Terrain.id)
            .where(
                and_(
                    Terrain.owner_id == owner_id,
                    Reservation.status != ReservationStatus.CANCELLED,
                    Reservation.start_datetime >= cutoff,
                )
            )
            .group_by(year_expr, month_expr)
            .order_by(year_expr.desc(), month_expr.desc())
        )
        return list((await self.db.execute(query)).all())
