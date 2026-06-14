import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.terrain import Terrain
from app.models.user import User, UserRole
from app.repositories.terrain_repository import TerrainRepository
from app.schemas.common import Page
from app.schemas.terrain import (
    TerrainCreate,
    TerrainResponse,
    TerrainSearchParams,
    TerrainSummary,
    TerrainUpdate,
)


class TerrainService:
    def __init__(self, db: AsyncSession):
        self.repo = TerrainRepository(db)

    # ── Côté propriétaire ─────────────────────────────────────────────────────

    async def create(self, owner: User, data: TerrainCreate) -> TerrainResponse:
        if owner.role not in (UserRole.OWNER, UserRole.ADMIN):
            raise ForbiddenException("Seuls les propriétaires peuvent créer un terrain")

        payload = data.model_dump()
        # Sérialiser OpeningHours (objet Pydantic) en dict brut pour le JSON
        payload["opening_hours"] = data.opening_hours.model_dump()
        payload["owner_id"] = owner.id

        terrain = await self.repo.create(payload)
        return TerrainResponse.model_validate(terrain)

    async def list_mine(
        self, owner: User, skip: int = 0, limit: int = 20
    ) -> Page[TerrainSummary]:
        terrains, total = await self.repo.get_by_owner(owner.id, skip=skip, limit=limit)
        return Page.build(
            items=[TerrainSummary.model_validate(t) for t in terrains],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def update(
        self, owner: User, terrain_id: uuid.UUID, data: TerrainUpdate
    ) -> TerrainResponse:
        terrain = await self._get_owned_or_raise(owner, terrain_id)

        payload = data.model_dump(exclude_none=True)
        if "opening_hours" in payload and data.opening_hours is not None:
            payload["opening_hours"] = data.opening_hours.model_dump()

        terrain = await self.repo.update(terrain, payload)
        return TerrainResponse.model_validate(terrain)

    async def delete(self, owner: User, terrain_id: uuid.UUID) -> None:
        terrain = await self._get_owned_or_raise(owner, terrain_id)
        await self.repo.delete(terrain)

    # ── Côté client ───────────────────────────────────────────────────────────

    async def list_active(
        self, params: TerrainSearchParams, skip: int = 0, limit: int = 20
    ) -> Page[TerrainSummary]:
        terrains, total = await self.repo.search(params, skip=skip, limit=limit)
        return Page.build(
            items=[TerrainSummary.model_validate(t) for t in terrains],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get_detail(self, terrain_id: uuid.UUID) -> TerrainResponse:
        terrain = await self.repo.get_active_by_id(terrain_id)
        if not terrain:
            raise NotFoundException("Terrain introuvable")
        return TerrainResponse.model_validate(terrain)

    # ── Commun ────────────────────────────────────────────────────────────────

    async def get_or_raise(self, terrain_id: uuid.UUID) -> Terrain:
        terrain = await self.repo.get(terrain_id)
        if not terrain:
            raise NotFoundException("Terrain introuvable")
        return terrain

    async def _get_owned_or_raise(self, owner: User, terrain_id: uuid.UUID) -> Terrain:
        """Récupère un terrain et vérifie la propriété (sauf admin)."""
        if owner.role == UserRole.ADMIN:
            return await self.get_or_raise(terrain_id)
        terrain = await self.repo.get_owner_terrain(terrain_id, owner.id)
        if not terrain:
            raise NotFoundException("Terrain introuvable ou vous n'en êtes pas propriétaire")
        return terrain
