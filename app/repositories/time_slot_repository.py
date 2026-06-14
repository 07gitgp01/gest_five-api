import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.time_slot import SlotStatus, TimeSlot
from app.repositories.base import BaseRepository


class TimeSlotRepository(BaseRepository[TimeSlot]):
    def __init__(self, db: AsyncSession):
        super().__init__(TimeSlot, db)

    # ── Lecture ───────────────────────────────────────────────────────────────

    async def get_available_by_terrain(
        self,
        terrain_id: uuid.UUID,
        date_from: datetime,
        date_to: datetime,
    ) -> list[TimeSlot]:
        """Créneaux AVAILABLE pour un terrain dans une plage de dates."""
        result = await self.db.execute(
            select(TimeSlot)
            .where(
                and_(
                    TimeSlot.terrain_id == terrain_id,
                    TimeSlot.status == SlotStatus.AVAILABLE,
                    TimeSlot.start_datetime >= date_from,
                    TimeSlot.end_datetime <= date_to,
                )
            )
            .order_by(TimeSlot.start_datetime)
        )
        return list(result.scalars().all())

    async def get_in_range(
        self,
        terrain_id: uuid.UUID,
        start: datetime,
        end: datetime,
        exclude_cancelled: bool = True,
    ) -> list[TimeSlot]:
        """Tous les créneaux qui chevauchent [start, end[."""
        query = select(TimeSlot).where(
            and_(
                TimeSlot.terrain_id == terrain_id,
                TimeSlot.start_datetime < end,
                TimeSlot.end_datetime > start,
            )
        )
        if exclude_cancelled:
            query = query.where(TimeSlot.status != SlotStatus.CANCELLED)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def find_conflicts(
        self,
        terrain_id: uuid.UUID,
        start: datetime,
        end: datetime,
        exclude_id: uuid.UUID | None = None,
    ) -> list[TimeSlot]:
        """Créneaux actifs (non annulés) qui chevauchent la plage demandée."""
        query = select(TimeSlot).where(
            and_(
                TimeSlot.terrain_id == terrain_id,
                TimeSlot.status != SlotStatus.CANCELLED,
                TimeSlot.start_datetime < end,
                TimeSlot.end_datetime > start,
            )
        )
        if exclude_id:
            query = query.where(TimeSlot.id != exclude_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_terrain(
        self,
        terrain_id: uuid.UUID,
        terrain_owner_id: uuid.UUID,  # conservé pour compatibilité signature — non utilisé en SQL
        skip: int = 0,
        limit: int = 50,
    ) -> list[TimeSlot]:
        """Tous les créneaux d'un terrain (gestion propriétaire)."""
        result = await self.db.execute(
            select(TimeSlot)
            .where(TimeSlot.terrain_id == terrain_id)
            .order_by(TimeSlot.start_datetime)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_for_update(self, slot_id: uuid.UUID) -> TimeSlot | None:
        """
        Acquiert un verrou exclusif SELECT … FOR UPDATE sur le créneau.

        Utilisé par les réservations slot-based pour sérialiser les écritures
        concurrentes et éliminer la race condition TOCTOU.
        No-op en SQLite (mono-writer) ; efficace en PostgreSQL.
        """
        result = await self.db.execute(
            select(TimeSlot).where(TimeSlot.id == slot_id).with_for_update()
        )
        return result.scalar_one_or_none()

    # ── Écriture ──────────────────────────────────────────────────────────────

    async def create_many(self, payloads: list[dict]) -> int:
        """Insertion en masse via INSERT bulk — retourne le nombre de créneaux créés."""
        if not payloads:
            return 0
        now = datetime.now(timezone.utc)
        for p in payloads:
            p.setdefault("created_at", now)
            p.setdefault("updated_at", now)
        await self.db.execute(insert(TimeSlot), payloads)
        await self.db.flush()
        return len(payloads)

    async def mark_booked(self, slot: TimeSlot) -> TimeSlot:
        return await self.update(slot, {"status": SlotStatus.BOOKED})

    async def mark_available(self, slot: TimeSlot) -> TimeSlot:
        return await self.update(slot, {"status": SlotStatus.AVAILABLE})

    # ── Filtrage pour la génération ───────────────────────────────────────────

    async def filter_non_conflicting(
        self,
        terrain_id: uuid.UUID,
        payloads: list[dict],
    ) -> tuple[list[dict], int]:
        """
        Retire les créneaux candidats qui chevauchent des créneaux existants.
        Retourne (payloads_propres, nb_ignorés).
        """
        if not payloads:
            return [], 0

        min_start = min(p["start_datetime"] for p in payloads)
        max_end = max(p["end_datetime"] for p in payloads)
        existing = await self.get_in_range(terrain_id, min_start, max_end)

        clean, skipped = [], 0
        for payload in payloads:
            p_start, p_end = payload["start_datetime"], payload["end_datetime"]
            has_conflict = any(
                s.start_datetime < p_end and s.end_datetime > p_start for s in existing
            )
            if has_conflict:
                skipped += 1
            else:
                clean.append(payload)

        return clean, skipped
