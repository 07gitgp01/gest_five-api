import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.terrain import Terrain, TerrainStatus
from app.repositories.base import BaseRepository
from app.schemas.terrain import TerrainSearchParams


class TerrainRepository(BaseRepository[Terrain]):
    def __init__(self, db: AsyncSession):
        super().__init__(Terrain, db)

    # ── Requête de base filtrée ───────────────────────────────────────────────

    def _apply_filters(self, query, params: TerrainSearchParams):
        """Applique les filtres de recherche sur une requête existante."""
        if params.city:
            query = query.where(Terrain.city.ilike(f"%{params.city}%"))
        if params.min_price is not None:
            query = query.where(Terrain.price_per_hour >= params.min_price)
        if params.max_price is not None:
            query = query.where(Terrain.price_per_hour <= params.max_price)
        if params.has_parking is not None:
            query = query.where(Terrain.has_parking == params.has_parking)
        if params.has_lighting is not None:
            query = query.where(Terrain.has_lighting == params.has_lighting)
        if params.has_changing_room is not None:
            query = query.where(Terrain.has_changing_room == params.has_changing_room)
        if params.has_shower is not None:
            query = query.where(Terrain.has_shower == params.has_shower)
        return query

    # ── Recherche publique ────────────────────────────────────────────────────

    async def search(
        self,
        params: TerrainSearchParams,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Terrain], int]:
        base = select(Terrain).where(Terrain.status == TerrainStatus.ACTIVE)
        base = self._apply_filters(base, params)

        count_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar_one()

        items_result = await self.db.execute(
            base.order_by(Terrain.average_rating.desc(), Terrain.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(items_result.scalars().all()), total

    async def get_active_by_id(self, terrain_id: uuid.UUID) -> Terrain | None:
        result = await self.db.execute(
            select(Terrain).where(
                and_(Terrain.id == terrain_id, Terrain.status == TerrainStatus.ACTIVE)
            )
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, terrain_id: uuid.UUID) -> Terrain | None:
        """
        Acquiert un verrou exclusif SELECT … FOR UPDATE sur le terrain.

        Utilisé par les réservations directes pour sérialiser les écritures
        concurrentes sur le même terrain et éliminer la race condition TOCTOU.
        No-op en SQLite (mono-writer par design) ; efficace en PostgreSQL.
        """
        result = await self.db.execute(
            select(Terrain).where(Terrain.id == terrain_id).with_for_update()
        )
        return result.scalar_one_or_none()

    # ── Espace propriétaire ───────────────────────────────────────────────────

    async def get_by_owner(
        self,
        owner_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Terrain], int]:
        base = select(Terrain).where(Terrain.owner_id == owner_id)

        count_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar_one()

        items_result = await self.db.execute(
            base.order_by(Terrain.created_at.desc()).offset(skip).limit(limit)
        )
        return list(items_result.scalars().all()), total

    async def get_owner_terrain(
        self, terrain_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Terrain | None:
        """Récupère un terrain uniquement si l'owner_id correspond."""
        result = await self.db.execute(
            select(Terrain).where(
                and_(Terrain.id == terrain_id, Terrain.owner_id == owner_id)
            )
        )
        return result.scalar_one_or_none()
