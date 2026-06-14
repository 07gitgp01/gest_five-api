import uuid
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import Reservation, ReservationStatus
from app.repositories.base import BaseRepository


class ReservationRepository(BaseRepository[Reservation]):
    def __init__(self, db: AsyncSession):
        super().__init__(Reservation, db)

    async def get_by_player(
        self, player_id: uuid.UUID, skip: int = 0, limit: int = 20
    ) -> list[Reservation]:
        result = await self.db.execute(
            select(Reservation)
            .where(Reservation.player_id == player_id)
            .order_by(Reservation.start_time.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_terrain(
        self, terrain_id: uuid.UUID, skip: int = 0, limit: int = 20
    ) -> list[Reservation]:
        result = await self.db.execute(
            select(Reservation)
            .where(Reservation.terrain_id == terrain_id)
            .order_by(Reservation.start_time.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def has_conflict(
        self,
        terrain_id: uuid.UUID,
        start: datetime,
        end: datetime,
        exclude_id: int | None = None,
    ) -> bool:
        query = select(Reservation).where(
            and_(
                Reservation.terrain_id == terrain_id,
                Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.CONFIRMED]),
                or_(and_(Reservation.start_time < end, Reservation.end_time > start)),
            )
        )
        if exclude_id:
            query = query.where(Reservation.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None
