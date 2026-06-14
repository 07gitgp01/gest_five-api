from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.reservation import ReservationCreate, ReservationResponse, ReservationUpdate
from app.services.reservation_service import ReservationService

router = APIRouter()


@router.get("/mine", response_model=list[ReservationResponse])
async def list_my_reservations(
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).list_mine(current_user, skip=skip, limit=limit)


@router.get("/{reservation_id}", response_model=ReservationResponse)
async def get_reservation(
    reservation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).get_or_raise(reservation_id)


@router.post("/", response_model=ReservationResponse, status_code=201)
async def create_reservation(
    data: ReservationCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).create(current_user, data)


@router.patch("/{reservation_id}/cancel", response_model=ReservationResponse)
async def cancel_reservation(
    reservation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).cancel(current_user, reservation_id)


@router.patch("/{reservation_id}/status", response_model=ReservationResponse)
async def update_reservation_status(
    reservation_id: int,
    data: ReservationUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ReservationService(db).update_status(current_user, reservation_id, data)
