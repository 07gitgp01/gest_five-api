import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import PaginationParams, get_current_active_user, require_owner_or_admin
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Page
from app.schemas.terrain import (
    TerrainCreate,
    TerrainResponse,
    TerrainSearchParams,
    TerrainSummary,
    TerrainUpdate,
)
from app.services.terrain_service import TerrainService

router = APIRouter()
logger = get_logger("gestfive.terrains")


# ── Dependency de filtres ──────────────────────────────────────────────────────

class TerrainFilters:
    def __init__(
        self,
        city: str | None = Query(default=None, description="Filtrer par ville"),
        min_price: float | None = Query(default=None, ge=0, description="Prix min (€/h)"),
        max_price: float | None = Query(default=None, ge=0, description="Prix max (€/h)"),
        has_parking: bool | None = Query(default=None),
        has_lighting: bool | None = Query(default=None),
        has_changing_room: bool | None = Query(default=None),
        has_shower: bool | None = Query(default=None),
    ):
        self.city = city
        self.min_price = min_price
        self.max_price = max_price
        self.has_parking = has_parking
        self.has_lighting = has_lighting
        self.has_changing_room = has_changing_room
        self.has_shower = has_shower

    def to_params(self) -> TerrainSearchParams:
        return TerrainSearchParams(
            city=self.city,
            min_price=self.min_price,
            max_price=self.max_price,
            has_parking=self.has_parking,
            has_lighting=self.has_lighting,
            has_changing_room=self.has_changing_room,
            has_shower=self.has_shower,
        )


# ── Endpoints publics ──────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=Page[TerrainSummary],
    summary="Lister les terrains",
    description="Liste paginée des terrains actifs avec filtres optionnels.",
)
async def list_terrains(
    filters: TerrainFilters = Depends(),
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
):
    return await TerrainService(db).list_active(
        filters.to_params(),
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get(
    "/owner/mine",
    response_model=Page[TerrainSummary],
    summary="Mes terrains",
    description="Liste paginée des terrains du propriétaire connecté.",
)
async def list_my_terrains(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await TerrainService(db).list_mine(
        current_user,
        skip=pagination.skip,
        limit=pagination.limit,
    )


@router.get(
    "/{terrain_id}",
    response_model=TerrainResponse,
    summary="Détail d'un terrain",
)
async def get_terrain(terrain_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await TerrainService(db).get_detail(terrain_id)


# ── Endpoints propriétaire ─────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=TerrainResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un terrain",
)
async def create_terrain(
    data: TerrainCreate,
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        terrain = await TerrainService(db).create(current_user, data)
        logger.info(
            "TERRAIN created — id=%s name=%r ville=%s owner_id=%s",
            terrain.id,
            getattr(data, "name", "?"),
            getattr(data, "city", "?"),
            current_user.id,
        )
        return terrain
    except HTTPException:
        raise
    except Exception:
        logger.exception("TERRAIN create erreur — owner_id=%s", current_user.id)
        raise


@router.patch(
    "/{terrain_id}",
    response_model=TerrainResponse,
    summary="Modifier un terrain",
)
async def update_terrain(
    terrain_id: uuid.UUID,
    data: TerrainUpdate,
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        terrain = await TerrainService(db).update(current_user, terrain_id, data)
        changed = list(data.model_dump(exclude_none=True).keys())
        logger.info(
            "TERRAIN updated — id=%s fields=%s owner_id=%s",
            terrain_id,
            changed,
            current_user.id,
        )
        return terrain
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "TERRAIN update erreur — id=%s owner_id=%s", terrain_id, current_user.id
        )
        raise


@router.delete(
    "/{terrain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un terrain",
    description="Suppression définitive. Les réservations associées sont supprimées en cascade.",
)
async def delete_terrain(
    terrain_id: uuid.UUID,
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        await TerrainService(db).delete(current_user, terrain_id)
        logger.info("TERRAIN deleted — id=%s owner_id=%s", terrain_id, current_user.id)
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "TERRAIN delete erreur — id=%s owner_id=%s", terrain_id, current_user.id
        )
        raise
