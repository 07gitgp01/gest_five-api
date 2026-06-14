import uuid
from datetime import datetime

from sqlalchemy import Float, and_, case, extract, func, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import cast

from app.core.config import settings
from app.models.payment import Payment, PaymentStatus
from app.models.reservation import Reservation, ReservationStatus
from app.models.terrain import Terrain, TerrainStatus
from app.models.user import User, UserRole


class AdminRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Utilisateurs ───────────────────────────────────────────────────────────

    async def list_users(
        self,
        q: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[User], int]:
        """Recherche textuelle dans prénom, nom, téléphone, email."""
        filters = []
        if q:
            pattern = f"%{q}%"
            filters.append(
                or_(
                    User.firstname.ilike(pattern),
                    User.lastname.ilike(pattern),
                    User.phone.ilike(pattern),
                    User.email.ilike(pattern),
                )
            )
        if role is not None:
            filters.append(User.role == role)
        if is_active is not None:
            filters.append(User.is_active == is_active)

        where = and_(*filters) if filters else True

        total = (
            await self.db.execute(
                select(func.count(User.id)).where(where)
            )
        ).scalar_one()

        items = list(
            (
                await self.db.execute(
                    select(User)
                    .where(where)
                    .order_by(User.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return items, total

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        return (
            await self.db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()

    # ── Terrains (JOIN owner pour le nom) ─────────────────────────────────────

    def _terrain_select(self):
        return select(
            Terrain.id,
            Terrain.owner_id,
            Terrain.name,
            Terrain.address,
            Terrain.city,
            Terrain.status,
            Terrain.price_per_hour,
            Terrain.average_rating,
            Terrain.created_at,
            Terrain.updated_at,
            (User.firstname + " " + User.lastname).label("owner_name"),
        ).join(User, Terrain.owner_id == User.id)

    async def list_terrains(
        self,
        status: TerrainStatus | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Row], int]:
        q = self._terrain_select()
        if status is not None:
            q = q.where(Terrain.status == status)

        total = (
            await self.db.execute(
                select(func.count(Terrain.id)).where(
                    Terrain.status == status if status else True
                )
            )
        ).scalar_one()

        rows = list(
            (
                await self.db.execute(
                    q.order_by(Terrain.created_at.desc()).offset(skip).limit(limit)
                )
            ).all()
        )
        return rows, total

    async def get_terrain_with_owner(self, terrain_id: uuid.UUID) -> Row | None:
        q = self._terrain_select().where(Terrain.id == terrain_id)
        return (await self.db.execute(q)).one_or_none()

    # ── Statistiques globales ─────────────────────────────────────────────────

    async def get_user_stats(self, month_start: datetime) -> Row:
        """Agrégation en une seule requête SQL."""
        query = select(
            func.count(User.id).label("total"),
            func.sum(case((User.is_active == True, 1), else_=0)).label("active"),  # noqa: E712
            func.sum(case((User.is_active == False, 1), else_=0)).label("inactive"),  # noqa: E712
            func.sum(case((User.role == UserRole.CLIENT, 1), else_=0)).label("clients"),
            func.sum(case((User.role == UserRole.OWNER, 1), else_=0)).label("owners"),
            func.sum(case((User.role == UserRole.ADMIN, 1), else_=0)).label("admins"),
            func.sum(
                case((User.created_at >= month_start, 1), else_=0)
            ).label("new_this_month"),
        )
        return (await self.db.execute(query)).one()

    async def get_terrain_stats(self) -> Row:
        query = select(
            func.count(Terrain.id).label("total"),
            func.sum(case((Terrain.status == TerrainStatus.ACTIVE, 1), else_=0)).label("active"),
            func.sum(case((Terrain.status == TerrainStatus.INACTIVE, 1), else_=0)).label("inactive"),
            func.sum(case((Terrain.status == TerrainStatus.MAINTENANCE, 1), else_=0)).label("maintenance"),
        )
        return (await self.db.execute(query)).one()

    async def get_reservation_and_revenue_stats(
        self, month_start: datetime
    ) -> Row:
        """Compteurs par statut + revenus (tout temps et mois en cours)."""
        not_cancelled = Reservation.status != ReservationStatus.CANCELLED
        month_cond = and_(not_cancelled, Reservation.start_datetime >= month_start)

        query = select(
            func.count(Reservation.id).label("total"),
            func.sum(case((Reservation.status == ReservationStatus.PENDING, 1), else_=0)).label("pending"),
            func.sum(case((Reservation.status == ReservationStatus.CONFIRMED, 1), else_=0)).label("confirmed"),
            func.sum(case((Reservation.status == ReservationStatus.COMPLETED, 1), else_=0)).label("completed"),
            func.sum(case((Reservation.status == ReservationStatus.CANCELLED, 1), else_=0)).label("cancelled"),
            func.coalesce(
                func.sum(case((not_cancelled, Reservation.total_price), else_=None)), 0.0
            ).label("total_revenue"),
            func.coalesce(
                func.sum(case((month_cond, Reservation.total_price), else_=None)), 0.0
            ).label("month_revenue"),
        )
        return (await self.db.execute(query)).one()

    async def get_payment_stats(self) -> int:
        """Nombre total de paiements réussis."""
        q = select(func.count(Payment.id)).where(
            Payment.status == PaymentStatus.SUCCESS
        )
        return (await self.db.execute(q)).scalar_one()

    # ── Croissance mensuelle ───────────────────────────────────────────────────

    async def get_users_by_month(self, cutoff: datetime) -> list[Row]:
        year_expr = extract("year", User.created_at)
        month_expr = extract("month", User.created_at)
        query = (
            select(
                year_expr.label("year"),
                month_expr.label("month"),
                func.count(User.id).label("count"),
            )
            .where(User.created_at >= cutoff)
            .group_by(year_expr, month_expr)
            .order_by(year_expr.desc(), month_expr.desc())
        )
        return list((await self.db.execute(query)).all())

    async def get_terrains_by_month(self, cutoff: datetime) -> list[Row]:
        year_expr = extract("year", Terrain.created_at)
        month_expr = extract("month", Terrain.created_at)
        query = (
            select(
                year_expr.label("year"),
                month_expr.label("month"),
                func.count(Terrain.id).label("count"),
            )
            .where(Terrain.created_at >= cutoff)
            .group_by(year_expr, month_expr)
            .order_by(year_expr.desc(), month_expr.desc())
        )
        return list((await self.db.execute(query)).all())

    async def get_reservations_by_month(self, cutoff: datetime) -> list[Row]:
        year_expr = extract("year", Reservation.start_datetime)
        month_expr = extract("month", Reservation.start_datetime)
        query = (
            select(
                year_expr.label("year"),
                month_expr.label("month"),
                func.count(Reservation.id).label("count"),
                func.coalesce(func.sum(Reservation.total_price), 0.0).label("revenue"),
            )
            .where(
                and_(
                    Reservation.start_datetime >= cutoff,
                    Reservation.status != ReservationStatus.CANCELLED,
                )
            )
            .group_by(year_expr, month_expr)
            .order_by(year_expr.desc(), month_expr.desc())
        )
        return list((await self.db.execute(query)).all())
