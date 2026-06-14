import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import Reservation, ReservationStatus
from app.models.terrain import Terrain
from app.repositories.base import BaseRepository


class ReservationRepository(BaseRepository[Reservation]):
    def __init__(self, db: AsyncSession):
        super().__init__(Reservation, db)

    async def get_by_player(
        self,
        player_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
        status: ReservationStatus | None = None,
    ) -> tuple[list[Reservation], int]:
        query = select(Reservation).where(Reservation.player_id == player_id)
        if status:
            query = query.where(Reservation.status == status)

        total = (await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )).scalar_one()

        result = await self.db.execute(
            query.order_by(Reservation.start_datetime.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all()), total

    async def get_by_terrain(
        self,
        terrain_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
        status: ReservationStatus | None = None,
    ) -> tuple[list[Reservation], int]:
        query = select(Reservation).where(Reservation.terrain_id == terrain_id)
        if status:
            query = query.where(Reservation.status == status)

        total = (await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )).scalar_one()

        result = await self.db.execute(
            query.order_by(Reservation.start_datetime.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all()), total

    async def get_by_owner_terrains(
        self,
        owner_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
        status: ReservationStatus | None = None,
    ) -> tuple[list[Reservation], int]:
        """Toutes les réservations sur les terrains appartenant à owner_id."""
        query = (
            select(Reservation)
            .join(Terrain, Reservation.terrain_id == Terrain.id)
            .where(Terrain.owner_id == owner_id)
        )
        if status:
            query = query.where(Reservation.status == status)

        total = (await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )).scalar_one()

        result = await self.db.execute(
            query.order_by(Reservation.start_datetime.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all()), total

    async def get_upcoming_for_reminder(
        self,
        window_start: datetime,
        window_end: datetime,
    ) -> list[Reservation]:
        """
        Réservations CONFIRMED dont le début est dans [window_start, window_end].
        Utilisé par le service de rappels pour cibler les matchs imminents.
        """
        query = select(Reservation).where(
            and_(
                Reservation.status == ReservationStatus.CONFIRMED,
                Reservation.start_datetime >= window_start,
                Reservation.start_datetime <= window_end,
            )
        )
        return list((await self.db.execute(query)).scalars().all())

    async def has_conflict(
        self,
        terrain_id: uuid.UUID,
        start: datetime,
        end: datetime,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        """Détecte un chevauchement [start, end[ avec des réservations actives."""
        query = select(Reservation).where(
            and_(
                Reservation.terrain_id == terrain_id,
                Reservation.status.in_(
                    [ReservationStatus.PENDING, ReservationStatus.CONFIRMED]
                ),
                or_(and_(Reservation.start_datetime < end, Reservation.end_datetime > start)),
            )
        )
        if exclude_id:
            query = query.where(Reservation.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None
