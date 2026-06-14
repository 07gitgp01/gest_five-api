import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    PaginationParams,
    get_current_active_user,
    require_owner_or_admin,
)
from app.db.session import get_db
from app.models.reservation import ReservationStatus
from app.models.user import User
from app.schemas.common import Page
from app.schemas.reservation import ReservationCreate, ReservationResponse, ReservationUpdate
from app.services.reservation_service import ReservationService

router = APIRouter()


# ── Client ────────────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=ReservationResponse,
    status_code=201,
    summary="Créer une réservation",
    description=(
        "Deux modes : **slot-based** (fournir `time_slot_id`) "
        "ou **direct** (fournir `terrain_id` + `start_datetime` + `end_datetime`)."
    ),
)
async def create_reservation(
    data: ReservationCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).create(current_user, data)


@router.get(
    "/mine",
    response_model=Page[ReservationResponse],
    summary="Historique du joueur",
)
async def list_my_reservations(
    pagination: PaginationParams = Depends(),
    status: Optional[ReservationStatus] = Query(default=None, description="Filtrer par statut"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).list_mine(
        current_user, skip=pagination.skip, limit=pagination.limit, status=status
    )


@router.get(
    "/mine/{reservation_id}",
    response_model=ReservationResponse,
    summary="Détail d'une réservation",
    description="Accessible au joueur concerné, au propriétaire du terrain ou à un admin.",
)
async def get_my_reservation(
    reservation_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).get_detail(current_user, reservation_id)


@router.patch(
    "/{reservation_id}/cancel",
    response_model=ReservationResponse,
    summary="Annuler une réservation",
    description="Le joueur annule la sienne ; un admin peut annuler n'importe laquelle.",
)
async def cancel_reservation(
    reservation_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).cancel(current_user, reservation_id)


# ── Propriétaire ──────────────────────────────────────────────────────────────

@router.get(
    "/owner/all",
    response_model=Page[ReservationResponse],
    summary="Toutes les réservations de l'owner",
    description="Vue consolidée de toutes les réservations sur les terrains du propriétaire.",
)
async def list_owner_reservations(
    pagination: PaginationParams = Depends(),
    status: Optional[ReservationStatus] = Query(default=None),
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).list_by_owner(
        current_user, skip=pagination.skip, limit=pagination.limit, status=status
    )


@router.get(
    "/terrain/{terrain_id}",
    response_model=Page[ReservationResponse],
    summary="Réservations d'un terrain",
    description="Le propriétaire consulte les réservations d'un de ses terrains.",
)
async def list_terrain_reservations(
    terrain_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    status: Optional[ReservationStatus] = Query(default=None),
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).list_by_terrain(
        current_user, terrain_id, skip=pagination.skip, limit=pagination.limit, status=status
    )


@router.patch(
    "/{reservation_id}/status",
    response_model=ReservationResponse,
    summary="Mettre à jour le statut",
    description="Propriétaire confirme (CONFIRMED) ou clôture (COMPLETED) une réservation.",
)
async def update_reservation_status(
    reservation_id: uuid.UUID,
    data: ReservationUpdate,
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).update_status(current_user, reservation_id, data)
