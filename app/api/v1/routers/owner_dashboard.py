from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_owner_or_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.owner_dashboard import (
    OwnerDashboard,
    PeakHour,
    RevenueSummary,
    TerrainOccupancy,
)
from app.services.owner_dashboard_service import OwnerDashboardService

router = APIRouter()


@router.get(
    "/me",
    response_model=OwnerDashboard,
    summary="Tableau de bord propriétaire complet",
    description=(
        "Synthèse en 6 requêtes SQL agrégées : statistiques revenus/réservations "
        "(aujourd'hui, mois, tout-temps), taux d'occupation par terrain, "
        "heures de pointe (3 derniers mois), revenus journaliers (7j) "
        "et mensuels (6 mois)."
    ),
)
async def get_owner_dashboard(
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await OwnerDashboardService(db).get_full_dashboard(current_user)


@router.get(
    "/me/occupancy",
    response_model=list[TerrainOccupancy],
    summary="Taux d'occupation par terrain",
    description=(
        "Heures réservées vs capacité d'exploitation pour le mois en cours. "
        "La capacité est calculée à partir des horaires d'ouverture de chaque terrain."
    ),
)
async def get_occupancy(
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await OwnerDashboardService(db).get_occupancy(current_user)


@router.get(
    "/me/peak-hours",
    response_model=list[PeakHour],
    summary="Heures les plus réservées",
    description=(
        "Classement des créneaux horaires par nombre de réservations non-annulées. "
        "Paramètre months : fenêtre d'analyse en mois (1–12)."
    ),
)
async def get_peak_hours(
    months: int = Query(default=3, ge=1, le=12),
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await OwnerDashboardService(db).get_peak_hours_summary(
        current_user, months=months
    )


@router.get(
    "/me/revenue",
    response_model=RevenueSummary,
    summary="Résumé des revenus",
    description=(
        "Revenus journaliers (7 derniers jours) et mensuels (6 derniers mois), "
        "hors réservations annulées."
    ),
)
async def get_revenue(
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await OwnerDashboardService(db).get_revenue_summary(current_user)
