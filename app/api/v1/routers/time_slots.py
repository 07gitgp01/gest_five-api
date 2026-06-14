import uuid
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_owner_or_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.time_slot import (
    AvailabilityResult,
    SlotGenerateRequest,
    SlotGenerateSummary,
    TimeSlotCreate,
    TimeSlotResponse,
    TimeSlotUpdate,
)
from app.services.availability_service import AvailabilityService

router = APIRouter()


# ── Disponibilité (public) ────────────────────────────────────────────────────

@router.get(
    "/{terrain_id}/availability",
    response_model=AvailabilityResult,
    summary="Vérifier la disponibilité",
    description="Vérifie si un créneau [start, end[ est libre sur le terrain.",
)
async def check_availability(
    terrain_id: uuid.UUID,
    start_datetime: datetime = Query(description="ISO 8601 avec timezone — ex: 2026-07-01T10:00:00Z"),
    end_datetime: datetime = Query(description="ISO 8601 avec timezone — ex: 2026-07-01T11:00:00Z"),
    db: AsyncSession = Depends(get_db),
):
    return await AvailabilityService(db).check(terrain_id, start_datetime, end_datetime)


@router.get(
    "/{terrain_id}/slots",
    response_model=list[TimeSlotResponse],
    summary="Créneaux disponibles",
    description="Liste les créneaux AVAILABLE pour une plage de dates.",
)
async def list_available_slots(
    terrain_id: uuid.UUID,
    date_from: date = Query(description="Date de début — ex: 2026-07-01"),
    date_to: date = Query(description="Date de fin — ex: 2026-07-07"),
    db: AsyncSession = Depends(get_db),
):
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
    end = datetime.combine(date_to, time.max, tzinfo=timezone.utc)
    return await AvailabilityService(db).list_available(terrain_id, start, end)


# ── Gestion des créneaux (propriétaire) ───────────────────────────────────────

@router.post(
    "/{terrain_id}/slots",
    response_model=TimeSlotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un créneau",
)
async def create_slot(
    terrain_id: uuid.UUID,
    data: TimeSlotCreate,
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AvailabilityService(db).create_slot(current_user, terrain_id, data)


@router.post(
    "/{terrain_id}/slots/generate",
    response_model=SlotGenerateSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Générer des créneaux en masse",
    description=(
        "Génère automatiquement des créneaux pour chaque jour ouvert "
        "entre date_from et date_to, selon les horaires d'ouverture du terrain. "
        "Les conflits avec des créneaux existants sont ignorés silencieusement."
    ),
)
async def generate_slots(
    terrain_id: uuid.UUID,
    data: SlotGenerateRequest,
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AvailabilityService(db).generate_slots(current_user, terrain_id, data)


@router.patch(
    "/{terrain_id}/slots/{slot_id}",
    response_model=TimeSlotResponse,
    summary="Modifier un créneau",
    description="Permet de bloquer/débloquer ou changer le prix d'un créneau.",
)
async def update_slot(
    terrain_id: uuid.UUID,
    slot_id: uuid.UUID,
    data: TimeSlotUpdate,
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AvailabilityService(db).update_slot(
        current_user, terrain_id, slot_id, data
    )


@router.delete(
    "/{terrain_id}/slots/{slot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un créneau",
    description="Impossible de supprimer un créneau déjà réservé.",
)
async def delete_slot(
    terrain_id: uuid.UUID,
    slot_id: uuid.UUID,
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    await AvailabilityService(db).delete_slot(current_user, terrain_id, slot_id)
