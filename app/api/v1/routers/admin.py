import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.terrain import TerrainStatus
from app.models.user import User, UserRole
from app.schemas.admin import (
    AdminTerrainResponse,
    AdminUserResponse,
    GrowthReport,
    PlatformStats,
    TerrainSuspendRequest,
    UserRoleUpdate,
)
from app.schemas.common import Page
from app.services.admin_service import AdminService

router = APIRouter()

# Tous les endpoints sont protégés par require_admin (rôle ADMIN obligatoire).


# ── Utilisateurs ──────────────────────────────────────────────────────────────

@router.get(
    "/users",
    response_model=Page[AdminUserResponse],
    summary="Liste et recherche des utilisateurs",
    description=(
        "Recherche textuelle (prénom, nom, téléphone, e-mail) via le paramètre `q`. "
        "Filtrages optionnels par rôle et statut is_active."
    ),
)
async def list_users(
    q: str | None = Query(default=None, description="Recherche textuelle"),
    role: UserRole | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).list_users(
        q=q, role=role, is_active=is_active, skip=skip, limit=limit
    )


@router.get(
    "/users/{user_id}",
    response_model=AdminUserResponse,
    summary="Détail d'un utilisateur",
)
async def get_user(
    user_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).get_user(user_id)


@router.patch(
    "/users/{user_id}/block",
    response_model=AdminUserResponse,
    summary="Bloquer / débloquer un utilisateur",
    description=(
        "Bascule `is_active`. Un compte désactivé ne peut plus se connecter. "
        "Un admin ne peut pas bloquer son propre compte."
    ),
)
async def toggle_block_user(
    user_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).toggle_block(current_user, user_id)


@router.patch(
    "/users/{user_id}/role",
    response_model=AdminUserResponse,
    summary="Changer le rôle d'un utilisateur",
    description="Un admin ne peut pas modifier son propre rôle.",
)
async def update_user_role(
    user_id: uuid.UUID,
    data: UserRoleUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).update_role(current_user, user_id, data)


# ── Terrains ──────────────────────────────────────────────────────────────────

@router.get(
    "/terrains",
    response_model=Page[AdminTerrainResponse],
    summary="Liste des terrains (tous statuts)",
    description="Filtrage optionnel par statut : active, inactive, maintenance.",
)
async def list_terrains(
    status: TerrainStatus | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).list_terrains(status=status, skip=skip, limit=limit)


@router.get(
    "/terrains/{terrain_id}",
    response_model=AdminTerrainResponse,
    summary="Détail d'un terrain (admin)",
)
async def get_terrain(
    terrain_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).get_terrain(terrain_id)


@router.patch(
    "/terrains/{terrain_id}/validate",
    response_model=AdminTerrainResponse,
    summary="Valider un terrain",
    description=(
        "Passe le terrain à ACTIVE et envoie une notification au propriétaire. "
        "Idempotent si le terrain est déjà actif."
    ),
)
async def validate_terrain(
    terrain_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).validate_terrain(terrain_id)


@router.patch(
    "/terrains/{terrain_id}/suspend",
    response_model=AdminTerrainResponse,
    summary="Suspendre un terrain",
    description=(
        "Passe le terrain à INACTIVE et notifie le propriétaire. "
        "Le motif est inclus dans la notification."
    ),
)
async def suspend_terrain(
    terrain_id: uuid.UUID,
    data: TerrainSuspendRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).suspend_terrain(terrain_id, data.reason)


# ── Statistiques ──────────────────────────────────────────────────────────────

@router.get(
    "/stats",
    response_model=PlatformStats,
    summary="Statistiques globales de la plateforme",
    description=(
        "Agrégations SQL en 4 requêtes : utilisateurs (par rôle, activité, mois), "
        "terrains (par statut), réservations (par statut), revenus (tout temps + mois)."
    ),
)
async def get_platform_stats(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).get_platform_stats()


@router.get(
    "/stats/growth",
    response_model=GrowthReport,
    summary="Rapport de croissance mensuelle",
    description=(
        "Nouveaux utilisateurs, nouveaux terrains, réservations et revenus "
        "par mois sur les N derniers mois. Inclut le taux de croissance vs le mois précédent."
    ),
)
async def get_growth_report(
    months: int = Query(default=6, ge=1, le=24),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).get_growth_report(months=months)
