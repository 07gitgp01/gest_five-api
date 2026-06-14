"""
Moteur central de disponibilité GestFive.

Responsabilités :
  1. Vérifier si un créneau [start, end[ est disponible sur un terrain
  2. Valider la conformité aux horaires d'ouverture
  3. Détecter les conflits avec des créneaux existants
  4. Générer des créneaux en masse depuis les horaires d'ouverture

Architecture extensible :
  - recurrence_rule sur TimeSlot → support futur des créneaux récurrents
  - SlotType (PEAK/OFF_PEAK) → hook pour tarification variable par heure
  - opening_hours sur Terrain → configuration par jour avec heures locales
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.terrain import Terrain, TerrainStatus
from app.models.time_slot import SlotStatus, SlotType, TimeSlot
from app.models.user import User, UserRole
from app.repositories.terrain_repository import TerrainRepository
from app.repositories.time_slot_repository import TimeSlotRepository
from app.schemas.time_slot import (
    AvailabilityResult,
    ConflictInfo,
    SlotGenerateRequest,
    SlotGenerateSummary,
    TimeSlotCreate,
    TimeSlotResponse,
    TimeSlotUpdate,
)


class AvailabilityService:
    def __init__(self, db: AsyncSession):
        self.slot_repo = TimeSlotRepository(db)
        self.terrain_repo = TerrainRepository(db)

    # ── Vérification de disponibilité ─────────────────────────────────────────

    async def check(
        self,
        terrain_id: uuid.UUID,
        start_datetime: datetime,
        end_datetime: datetime,
        exclude_slot_id: uuid.UUID | None = None,
    ) -> AvailabilityResult:
        """
        Vérifie la disponibilité d'un créneau en 3 étapes :
        1. Terrain actif et existant
        2. Dans les horaires d'ouverture
        3. Pas de conflit avec un créneau existant
        """
        terrain = await self.terrain_repo.get(terrain_id)
        if not terrain or terrain.status != TerrainStatus.ACTIVE:
            return AvailabilityResult(
                available=False,
                terrain_id=terrain_id,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                reason="Terrain inactif ou introuvable",
            )

        is_open, reason = self._check_opening_hours(
            terrain.opening_hours, start_datetime, end_datetime
        )
        if not is_open:
            return AvailabilityResult(
                available=False,
                terrain_id=terrain_id,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                reason=reason,
            )

        conflicts = await self.slot_repo.find_conflicts(
            terrain_id, start_datetime, end_datetime, exclude_slot_id
        )
        if conflicts:
            return AvailabilityResult(
                available=False,
                terrain_id=terrain_id,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                reason=f"{len(conflicts)} conflit(s) détecté(s)",
                conflicts=[
                    ConflictInfo(
                        slot_id=s.id,
                        start_datetime=s.start_datetime,
                        end_datetime=s.end_datetime,
                        status=s.status,
                    )
                    for s in conflicts
                ],
            )

        return AvailabilityResult(
            available=True,
            terrain_id=terrain_id,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
        )

    # ── Gestion des créneaux (propriétaire) ───────────────────────────────────

    async def create_slot(
        self, owner: User, terrain_id: uuid.UUID, data: TimeSlotCreate
    ) -> TimeSlotResponse:
        terrain = await self._get_owned_terrain(owner, terrain_id)

        result = await self.check(terrain_id, data.start_datetime, data.end_datetime)
        if not result.available:
            raise BadRequestException(result.reason or "Créneau non disponible")

        slot = await self.slot_repo.create(
            {
                "terrain_id": terrain.id,
                "start_datetime": data.start_datetime,
                "end_datetime": data.end_datetime,
                "slot_type": data.slot_type,
                "price_override": data.price_override,
                "notes": data.notes,
                "status": SlotStatus.AVAILABLE,
            }
        )
        return TimeSlotResponse.model_validate(slot)

    async def update_slot(
        self,
        owner: User,
        terrain_id: uuid.UUID,
        slot_id: uuid.UUID,
        data: TimeSlotUpdate,
    ) -> TimeSlotResponse:
        await self._get_owned_terrain(owner, terrain_id)
        slot = await self._get_slot_or_raise(slot_id, terrain_id)

        if slot.status == SlotStatus.BOOKED and data.status == SlotStatus.CANCELLED:
            raise BadRequestException(
                "Annulez d'abord la réservation associée avant de supprimer ce créneau"
            )

        updated = await self.slot_repo.update(slot, data.model_dump(exclude_none=True))
        return TimeSlotResponse.model_validate(updated)

    async def delete_slot(
        self, owner: User, terrain_id: uuid.UUID, slot_id: uuid.UUID
    ) -> None:
        await self._get_owned_terrain(owner, terrain_id)
        slot = await self._get_slot_or_raise(slot_id, terrain_id)
        if slot.status == SlotStatus.BOOKED:
            raise BadRequestException(
                "Impossible de supprimer un créneau déjà réservé"
            )
        await self.slot_repo.delete(slot)

    async def generate_slots(
        self,
        owner: User,
        terrain_id: uuid.UUID,
        request: SlotGenerateRequest,
    ) -> SlotGenerateSummary:
        """
        Génère automatiquement des créneaux pour chaque jour ouvert
        de date_from à date_to selon les horaires d'ouverture du terrain.
        """
        terrain = await self._get_owned_terrain(owner, terrain_id)

        if not terrain.opening_hours:
            raise BadRequestException(
                "Le terrain n'a pas d'horaires d'ouverture définis. "
                "Configurez-les via PATCH /terrains/{id}"
            )

        payloads = self._build_slot_payloads(terrain, request)

        clean_payloads, skipped = await self.slot_repo.filter_non_conflicting(
            terrain_id=terrain.id, payloads=payloads
        )
        created = await self.slot_repo.create_many(clean_payloads)

        return SlotGenerateSummary(
            terrain_id=terrain.id,
            date_from=request.date_from,
            date_to=request.date_to,
            created_count=created,
            skipped_count=skipped,
        )

    # ── Lecture publique ──────────────────────────────────────────────────────

    async def list_available(
        self,
        terrain_id: uuid.UUID,
        date_from: datetime,
        date_to: datetime,
    ) -> list[TimeSlotResponse]:
        slots = await self.slot_repo.get_available_by_terrain(terrain_id, date_from, date_to)
        return [TimeSlotResponse.model_validate(s) for s in slots]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _check_opening_hours(
        self, opening_hours: dict, start: datetime, end: datetime
    ) -> tuple[bool, str]:
        """
        Vérifie que [start, end[ est dans les horaires d'ouverture.
        Retourne (is_open, message_raison).
        """
        if not opening_hours:
            return True, ""  # pas d'horaires définis → ouvert par défaut

        if start.date() != end.date():
            return False, "Un créneau ne peut pas dépasser minuit"

        day_name = start.strftime("%A").lower()
        day = opening_hours.get(day_name)

        if not day:
            return False, f"Aucun horaire défini pour le {day_name}"

        if day.get("is_closed", False):
            return False, f"Terrain fermé le {day_name}"

        open_h, open_m = map(int, day.get("open", "00:00").split(":"))
        close_h, close_m = map(int, day.get("close", "23:59").split(":"))

        open_t = time(open_h, open_m)
        close_t = time(close_h, close_m)
        slot_start_t = time(start.hour, start.minute)
        slot_end_t = time(end.hour, end.minute)

        if slot_start_t < open_t:
            return False, f"Avant l'ouverture ({day['open']})"
        if slot_end_t > close_t:
            return False, f"Après la fermeture ({day['close']})"

        return True, ""

    def _build_slot_payloads(
        self, terrain: Terrain, request: SlotGenerateRequest
    ) -> list[dict]:
        """Construit la liste des créneaux candidats depuis les horaires d'ouverture."""
        payloads: list[dict] = []
        duration = timedelta(minutes=request.duration_minutes)
        now = datetime.now(timezone.utc)
        current = request.date_from

        while current <= request.date_to:
            day_name = current.strftime("%A").lower()
            day = terrain.opening_hours.get(day_name, {})

            if not day.get("is_closed", True):
                open_h, open_m = map(int, day.get("open", "08:00").split(":"))
                close_h, close_m = map(int, day.get("close", "22:00").split(":"))

                slot_start = datetime(
                    current.year, current.month, current.day,
                    open_h, open_m, tzinfo=timezone.utc
                )
                day_close = datetime(
                    current.year, current.month, current.day,
                    close_h, close_m, tzinfo=timezone.utc
                )

                while slot_start + duration <= day_close:
                    slot_end = slot_start + duration
                    if slot_start > now:
                        payloads.append({
                            "id": uuid.uuid4(),
                            "terrain_id": terrain.id,
                            "start_datetime": slot_start,
                            "end_datetime": slot_end,
                            "slot_type": request.slot_type,
                            "status": SlotStatus.AVAILABLE,
                            "price_override": request.price_override,
                            "recurrence_rule": None,
                            "notes": None,
                        })
                    slot_start += duration

            current += timedelta(days=1)

        return payloads

    async def _get_owned_terrain(self, owner: User, terrain_id: uuid.UUID) -> Terrain:
        terrain = await self.terrain_repo.get(terrain_id)
        if not terrain:
            raise NotFoundException("Terrain introuvable")
        if terrain.owner_id != owner.id and owner.role != UserRole.ADMIN:
            raise ForbiddenException("Vous n'êtes pas propriétaire de ce terrain")
        return terrain

    async def _get_slot_or_raise(
        self, slot_id: uuid.UUID, terrain_id: uuid.UUID
    ) -> TimeSlot:
        slot = await self.slot_repo.get(slot_id)
        if not slot or slot.terrain_id != terrain_id:
            raise NotFoundException("Créneau introuvable")
        return slot

    def compute_effective_price(self, slot: TimeSlot, terrain: Terrain) -> float:
        """
        Prix effectif d'un créneau :
        - price_override si défini
        - sinon terrain.price_per_hour × durée en heures
        Extensibilité : SlotType.PEAK peut appliquer un multiplicateur.
        """
        if slot.price_override is not None:
            return slot.price_override

        duration_h = (slot.end_datetime - slot.start_datetime).total_seconds() / 3600
        base_price = terrain.price_per_hour * duration_h

        # Hook pour tarification variable (PEAK = +50%, OFF_PEAK = -20%)
        multiplier = {
            SlotType.PEAK: 1.5,
            SlotType.OFF_PEAK: 0.8,
            SlotType.REGULAR: 1.0,
        }.get(slot.slot_type, 1.0)

        return round(base_price * multiplier, 2)
