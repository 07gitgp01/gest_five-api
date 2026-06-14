from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Page
from app.schemas.dashboard import HistoryItem, PlayerDashboard, UpcomingReservation
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get(
    "/me",
    response_model=PlayerDashboard,
    summary="Tableau de bord complet",
    description=(
        "Vue synthétique en une seule requête agrégée par catégorie : "
        "5 prochaines réservations, statistiques globales (heures jouées, "
        "montant dépensé, compteurs par statut), terrain préféré, "
        "statistiques des 6 derniers mois."
    ),
)
async def get_my_dashboard(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await DashboardService(db).get_full_dashboard(current_user)


@router.get(
    "/me/upcoming",
    response_model=list[UpcomingReservation],
    summary="Prochaines réservations",
    description=(
        "Réservations futures avec statut PENDING ou CONFIRMED, "
        "ordonnées par date croissante. Limite configurable (1–50)."
    ),
)
async def get_upcoming(
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await DashboardService(db).get_upcoming(current_user, limit=limit)


@router.get(
    "/me/history",
    response_model=Page[HistoryItem],
    summary="Historique des réservations",
    description=(
        "Réservations passées et annulées, ordonnées par date décroissante. "
        "Paginées via skip/limit."
    ),
)
async def get_history(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await DashboardService(db).get_history(current_user, skip=skip, limit=limit)
