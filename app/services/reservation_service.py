"""
Service de réservation GestFive.

Gestion de la concurrence :
  - Réservation slot-based  → SELECT … FOR UPDATE sur le créneau (TimeSlot)
    → sérialise les tentatives concurrentes sur le même créneau.
  - Réservation directe     → SELECT … FOR UPDATE sur le terrain (Terrain)
    → sérialise les réservations directes par terrain ; la détection de conflit
    s'exécute à l'intérieur du verrou, sans fenêtre TOCTOU.

Gestion des transactions :
  - Les notifications best-effort s'exécutent dans un savepoint (begin_nested).
    Si elles échouent, seul le savepoint est rollbacké ; la session principale
    reste valide et le commit de la réservation/annulation n'est pas affecté.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, ForbiddenException, NotFoundException
from app.models.reservation import Reservation, ReservationStatus
from app.models.time_slot import SlotStatus
from app.models.user import User, UserRole
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.terrain_repository import TerrainRepository
from app.repositories.time_slot_repository import TimeSlotRepository
from app.schemas.common import Page
from app.schemas.reservation import ReservationCreate, ReservationResponse, ReservationUpdate
from app.services.availability_service import AvailabilityService


class ReservationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ReservationRepository(db)
        self.terrain_repo = TerrainRepository(db)
        self.slot_repo = TimeSlotRepository(db)
        self.availability = AvailabilityService(db)

    # ── Création ──────────────────────────────────────────────────────────────

    async def create(self, player: User, data: ReservationCreate) -> ReservationResponse:
        if data.time_slot_id:
            res = await self._create_from_slot(player, data)
        else:
            res = await self._create_direct(player, data)
        return ReservationResponse.model_validate(res)

    async def _create_from_slot(self, player: User, data: ReservationCreate) -> Reservation:
        """
        Réservation via un créneau pré-défini.

        Pattern anti-race-condition :
          1. SELECT … FOR UPDATE sur le créneau → verrou exclusif PostgreSQL
          2. Re-vérification du statut sous verrou
          3. Création de la réservation + mise à jour du statut du créneau
          → Les étapes 2-3 sont atomiques : aucune autre transaction ne peut
            interrompre le bloc entre l'acquisition du verrou et le commit.
        """
        # Verrou exclusif — bloque toute tentative concurrente sur ce créneau
        slot = await self.slot_repo.get_for_update(data.time_slot_id)
        if not slot:
            raise NotFoundException("Créneau introuvable")
        # Re-check sous verrou (le statut a pu changer avant l'acquisition)
        if slot.status != SlotStatus.AVAILABLE:
            raise BadRequestException(
                f"Ce créneau n'est plus disponible (statut : {slot.status})"
            )
        if slot.start_datetime < datetime.now(timezone.utc):
            raise BadRequestException("Ce créneau est dans le passé")

        terrain = await self.terrain_repo.get(slot.terrain_id)
        if not terrain:
            raise NotFoundException("Terrain introuvable")

        total_price = self.availability.compute_effective_price(slot, terrain)

        try:
            reservation = await self.repo.create({
                "terrain_id": slot.terrain_id,
                "player_id": player.id,
                "time_slot_id": slot.id,
                "start_datetime": slot.start_datetime,
                "end_datetime": slot.end_datetime,
                "total_price": total_price,
                "notes": data.notes,
            })
        except IntegrityError:
            raise ConflictException("Ce créneau vient d'être réservé par un autre joueur")

        await self.slot_repo.mark_booked(slot)
        return reservation

    async def _create_direct(self, player: User, data: ReservationCreate) -> Reservation:
        """
        Réservation directe (sans créneau pré-défini).

        Pattern anti-race-condition :
          1. SELECT … FOR UPDATE sur le terrain → sérialise les réservations directes
          2. Vérification disponibilité + conflits sous verrou
          3. Création de la réservation
          → Aucune autre réservation directe sur ce terrain ne peut s'intercaler
            entre la vérification et l'insertion.
        """
        if data.start_datetime < datetime.now(timezone.utc):
            raise BadRequestException("La date de réservation ne peut pas être dans le passé")

        # Verrou exclusif sur le terrain — sérialise les bookings directs par terrain
        terrain = await self.terrain_repo.get_for_update(data.terrain_id)
        if not terrain:
            raise NotFoundException("Terrain introuvable")

        # Vérifications sous verrou — pas de fenêtre TOCTOU possible
        availability = await self.availability.check(
            data.terrain_id, data.start_datetime, data.end_datetime
        )
        if not availability.available:
            raise BadRequestException(availability.reason or "Créneau non disponible")

        if await self.repo.has_conflict(data.terrain_id, data.start_datetime, data.end_datetime):
            raise BadRequestException("Ce créneau est déjà réservé par un autre joueur")

        duration_h = (data.end_datetime - data.start_datetime).total_seconds() / 3600
        total_price = round(duration_h * terrain.price_per_hour, 2)

        try:
            return await self.repo.create({
                "terrain_id": data.terrain_id,
                "player_id": player.id,
                "time_slot_id": None,
                "start_datetime": data.start_datetime,
                "end_datetime": data.end_datetime,
                "total_price": total_price,
                "notes": data.notes,
            })
        except IntegrityError:
            raise ConflictException("Ce créneau vient d'être réservé par un autre joueur")

    # ── Lecture ───────────────────────────────────────────────────────────────

    async def get_or_raise(self, reservation_id: uuid.UUID) -> Reservation:
        reservation = await self.repo.get(reservation_id)
        if not reservation:
            raise NotFoundException("Réservation introuvable")
        return reservation

    async def get_detail(
        self, user: User, reservation_id: uuid.UUID
    ) -> ReservationResponse:
        """Accessible au joueur, au propriétaire du terrain ou à un admin."""
        reservation = await self.get_or_raise(reservation_id)

        if user.role == UserRole.ADMIN or reservation.player_id == user.id:
            return ReservationResponse.model_validate(reservation)

        terrain = await self.terrain_repo.get(reservation.terrain_id)
        if terrain and terrain.owner_id == user.id:
            return ReservationResponse.model_validate(reservation)

        raise ForbiddenException()

    async def list_mine(
        self,
        player: User,
        skip: int = 0,
        limit: int = 20,
        status: ReservationStatus | None = None,
    ) -> Page[ReservationResponse]:
        items, total = await self.repo.get_by_player(
            player.id, skip=skip, limit=limit, status=status
        )
        return Page.build(
            items=[ReservationResponse.model_validate(r) for r in items],
            total=total, skip=skip, limit=limit,
        )

    async def list_by_terrain(
        self,
        owner: User,
        terrain_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
        status: ReservationStatus | None = None,
    ) -> Page[ReservationResponse]:
        terrain = await self.terrain_repo.get(terrain_id)
        if not terrain:
            raise NotFoundException("Terrain introuvable")
        if owner.role != UserRole.ADMIN and terrain.owner_id != owner.id:
            raise ForbiddenException("Vous n'êtes pas propriétaire de ce terrain")

        items, total = await self.repo.get_by_terrain(
            terrain_id, skip=skip, limit=limit, status=status
        )
        return Page.build(
            items=[ReservationResponse.model_validate(r) for r in items],
            total=total, skip=skip, limit=limit,
        )

    async def list_by_owner(
        self,
        owner: User,
        skip: int = 0,
        limit: int = 20,
        status: ReservationStatus | None = None,
    ) -> Page[ReservationResponse]:
        """Toutes les réservations sur les terrains de l'owner (tableau de bord propriétaire)."""
        items, total = await self.repo.get_by_owner_terrains(
            owner.id, skip=skip, limit=limit, status=status
        )
        return Page.build(
            items=[ReservationResponse.model_validate(r) for r in items],
            total=total, skip=skip, limit=limit,
        )

    # ── Mutations ─────────────────────────────────────────────────────────────

    async def cancel(self, user: User, reservation_id: uuid.UUID) -> ReservationResponse:
        reservation = await self.get_or_raise(reservation_id)

        if reservation.player_id != user.id and user.role != UserRole.ADMIN:
            raise ForbiddenException()
        if reservation.status not in (ReservationStatus.PENDING, ReservationStatus.CONFIRMED):
            raise BadRequestException(
                f"Impossible d'annuler une réservation avec le statut : {reservation.status}"
            )

        updated = await self.repo.update(reservation, {"status": ReservationStatus.CANCELLED})

        if reservation.time_slot_id:
            slot = await self.slot_repo.get(reservation.time_slot_id)
            if slot and slot.status == SlotStatus.BOOKED:
                await self.slot_repo.mark_available(slot)

        # Notification dans un savepoint — si elle échoue, seul le savepoint est rollbacké ;
        # l'annulation elle-même n'est pas affectée.
        try:
            from app.services.notification_service import NotificationService
            async with self.db.begin_nested():
                await NotificationService(self.db).on_cancellation(updated)
        except Exception:
            pass

        return ReservationResponse.model_validate(updated)

    async def update_status(
        self, owner: User, reservation_id: uuid.UUID, data: ReservationUpdate
    ) -> ReservationResponse:
        """Propriétaire confirme (CONFIRMED) ou clôture (COMPLETED) une réservation."""
        reservation = await self.get_or_raise(reservation_id)

        if owner.role != UserRole.ADMIN:
            terrain = await self.terrain_repo.get(reservation.terrain_id)
            if not terrain or terrain.owner_id != owner.id:
                raise ForbiddenException()

        updated = await self.repo.update(reservation, data.model_dump(exclude_none=True))
        return ReservationResponse.model_validate(updated)
