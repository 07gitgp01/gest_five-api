import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.reservation import Reservation, ReservationStatus
from app.models.user import User, UserRole
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.terrain_repository import TerrainRepository
from app.schemas.reservation import ReservationCreate, ReservationUpdate


class ReservationService:
    def __init__(self, db: AsyncSession):
        self.repo = ReservationRepository(db)
        self.terrain_repo = TerrainRepository(db)

    async def create(self, player: User, data: ReservationCreate) -> Reservation:
        terrain = await self.terrain_repo.get(data.terrain_id)
        if not terrain:
            raise NotFoundException("Terrain introuvable")

        if data.start_time < datetime.now(timezone.utc):
            raise BadRequestException("La date de réservation ne peut pas être dans le passé")

        if await self.repo.has_conflict(data.terrain_id, data.start_time, data.end_time):
            raise BadRequestException("Ce créneau est déjà réservé")

        duration_hours = (data.end_time - data.start_time).total_seconds() / 3600
        total_price = round(duration_hours * terrain.price_per_hour, 2)

        return await self.repo.create(
            {
                **data.model_dump(),
                "player_id": player.id,
                "total_price": total_price,
            }
        )

    async def get_or_raise(self, reservation_id: int) -> Reservation:
        reservation = await self.repo.get(reservation_id)
        if not reservation:
            raise NotFoundException("Réservation introuvable")
        return reservation

    async def list_mine(
        self, player: User, skip: int = 0, limit: int = 20
    ) -> list[Reservation]:
        return await self.repo.get_by_player(player.id, skip=skip, limit=limit)

    async def cancel(self, user: User, reservation_id: int) -> Reservation:
        reservation = await self.get_or_raise(reservation_id)
        if reservation.player_id != user.id and user.role != UserRole.ADMIN:
            raise ForbiddenException()
        if reservation.status not in (ReservationStatus.PENDING, ReservationStatus.CONFIRMED):
            raise BadRequestException("Cette réservation ne peut pas être annulée")
        return await self.repo.update(reservation, {"status": ReservationStatus.CANCELLED})

    async def update_status(
        self, owner: User, reservation_id: int, data: ReservationUpdate
    ) -> Reservation:
        reservation = await self.get_or_raise(reservation_id)
        if owner.role != UserRole.ADMIN:
            terrain = await self.terrain_repo.get(reservation.terrain_id)
            if not terrain or terrain.owner_id != owner.id:
                raise ForbiddenException()
        return await self.repo.update(reservation, data.model_dump(exclude_none=True))
