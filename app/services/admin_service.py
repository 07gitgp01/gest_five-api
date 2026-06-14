import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import FR_MONTHS, empty_month, month_label
from app.core.exceptions import BadRequestException, NotFoundException
from app.models.notification import NotificationType
from app.models.terrain import TerrainStatus
from app.models.user import User, UserRole
from app.repositories.admin_repository import AdminRepository
from app.repositories.terrain_repository import TerrainRepository
from app.repositories.user_repository import UserRepository
from app.schemas.admin import (
    AdminTerrainResponse,
    AdminUserResponse,
    GrowthReport,
    MonthlyGrowth,
    PlatformStats,
    ReservationStats,
    RevenueStats,
    TerrainStats,
    UserRoleUpdate,
    UserStats,
)
from app.schemas.common import Page


class AdminService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AdminRepository(db)
        self.terrain_repo = TerrainRepository(db)
        self.user_repo = UserRepository(db)

    # ── Utilisateurs ───────────────────────────────────────────────────────────

    async def list_users(
        self,
        q: str | None,
        role: UserRole | None,
        is_active: bool | None,
        skip: int,
        limit: int,
    ) -> Page[AdminUserResponse]:
        items, total = await self.repo.list_users(
            q=q, role=role, is_active=is_active, skip=skip, limit=limit
        )
        return Page.build(
            items=[AdminUserResponse.model_validate(u) for u in items],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get_user(self, user_id: uuid.UUID) -> AdminUserResponse:
        user = await self.repo.get_user(user_id)
        if not user:
            raise NotFoundException("Utilisateur introuvable")
        return AdminUserResponse.model_validate(user)

    async def toggle_block(self, admin: User, user_id: uuid.UUID) -> AdminUserResponse:
        """Bascule is_active. Un admin ne peut pas se bloquer lui-même."""
        if admin.id == user_id:
            raise BadRequestException("Impossible de bloquer votre propre compte")

        user = await self.repo.get_user(user_id)
        if not user:
            raise NotFoundException("Utilisateur introuvable")

        updated = await self.user_repo.update(user, {"is_active": not user.is_active})
        return AdminUserResponse.model_validate(updated)

    async def update_role(
        self, admin: User, user_id: uuid.UUID, data: UserRoleUpdate
    ) -> AdminUserResponse:
        """L'admin ne peut pas changer son propre rôle."""
        if admin.id == user_id:
            raise BadRequestException("Impossible de modifier votre propre rôle")

        user = await self.repo.get_user(user_id)
        if not user:
            raise NotFoundException("Utilisateur introuvable")

        updated = await self.user_repo.update(user, {"role": data.role})
        return AdminUserResponse.model_validate(updated)

    # ── Terrains ───────────────────────────────────────────────────────────────

    async def list_terrains(
        self,
        status: TerrainStatus | None,
        skip: int,
        limit: int,
    ) -> Page[AdminTerrainResponse]:
        rows, total = await self.repo.list_terrains(status=status, skip=skip, limit=limit)
        return Page.build(
            items=[_terrain_from_row(r) for r in rows],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get_terrain(self, terrain_id: uuid.UUID) -> AdminTerrainResponse:
        row = await self.repo.get_terrain_with_owner(terrain_id)
        if not row:
            raise NotFoundException("Terrain introuvable")
        return _terrain_from_row(row)

    async def validate_terrain(self, terrain_id: uuid.UUID) -> AdminTerrainResponse:
        """Passe le terrain à ACTIVE et notifie le propriétaire dans un savepoint."""
        terrain = await self.terrain_repo.get(terrain_id)
        if not terrain:
            raise NotFoundException("Terrain introuvable")

        await self.terrain_repo.update(terrain, {"status": TerrainStatus.ACTIVE})

        try:
            from app.services.notification_service import NotificationService
            async with self.db.begin_nested():
                await NotificationService(self.db).notify(
                    user_id=terrain.owner_id,
                    type=NotificationType.GENERAL,
                    title="Terrain validé ✓",
                    body=(
                        f"Votre terrain « {terrain.name} » a été validé par un administrateur "
                        "et est maintenant visible sur la plateforme."
                    ),
                    data={"terrain_id": str(terrain.id)},
                )
        except Exception:
            pass

        row = await self.repo.get_terrain_with_owner(terrain_id)
        return _terrain_from_row(row)

    async def suspend_terrain(
        self, terrain_id: uuid.UUID, reason: str
    ) -> AdminTerrainResponse:
        """Passe le terrain à INACTIVE et notifie le propriétaire dans un savepoint."""
        terrain = await self.terrain_repo.get(terrain_id)
        if not terrain:
            raise NotFoundException("Terrain introuvable")

        await self.terrain_repo.update(terrain, {"status": TerrainStatus.INACTIVE})

        try:
            from app.services.notification_service import NotificationService
            body = f"Votre terrain « {terrain.name} » a été suspendu par un administrateur."
            if reason:
                body += f" Motif : {reason}"
            async with self.db.begin_nested():
                await NotificationService(self.db).notify(
                    user_id=terrain.owner_id,
                    type=NotificationType.GENERAL,
                    title="Terrain suspendu",
                    body=body,
                    data={"terrain_id": str(terrain.id), "reason": reason},
                )
        except Exception:
            pass

        row = await self.repo.get_terrain_with_owner(terrain_id)
        return _terrain_from_row(row)

    # ── Statistiques ───────────────────────────────────────────────────────────

    async def get_platform_stats(self) -> PlatformStats:
        """4 requêtes SQL agrégées — aucun N+1."""
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        u = await self.repo.get_user_stats(month_start)
        t = await self.repo.get_terrain_stats()
        r = await self.repo.get_reservation_and_revenue_stats(month_start)
        p = await self.repo.get_payment_stats()

        return PlatformStats(
            users=UserStats(
                total=u.total or 0,
                active=int(u.active or 0),
                inactive=int(u.inactive or 0),
                clients=int(u.clients or 0),
                owners=int(u.owners or 0),
                admins=int(u.admins or 0),
                new_this_month=int(u.new_this_month or 0),
            ),
            terrains=TerrainStats(
                total=t.total or 0,
                active=int(t.active or 0),
                inactive=int(t.inactive or 0),
                maintenance=int(t.maintenance or 0),
            ),
            reservations=ReservationStats(
                total=r.total or 0,
                pending=int(r.pending or 0),
                confirmed=int(r.confirmed or 0),
                completed=int(r.completed or 0),
                cancelled=int(r.cancelled or 0),
            ),
            revenue=RevenueStats(
                total_revenue=round(float(r.total_revenue or 0), 2),
                month_revenue=round(float(r.month_revenue or 0), 2),
                total_successful_payments=p,
            ),
        )

    async def get_growth_report(self, months: int = 6) -> GrowthReport:
        """
        Croise 3 jeux de données GROUP BY mois.
        Fusion en Python dans un dict (year, month) — évite une requête UNION complexe.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)

        user_rows = await self.repo.get_users_by_month(cutoff)
        terrain_rows = await self.repo.get_terrains_by_month(cutoff)
        res_rows = await self.repo.get_reservations_by_month(cutoff)

        # Fusion par clé (year, month) — empty_month() fournit les zéros par défaut
        merged: dict[tuple[int, int], dict] = {}

        for row in user_rows:
            key = (int(row.year), int(row.month))
            merged.setdefault(key, empty_month(key[0], key[1]))
            merged[key]["new_users"] = int(row.count)

        for row in terrain_rows:
            key = (int(row.year), int(row.month))
            merged.setdefault(key, empty_month(key[0], key[1]))
            merged[key]["new_terrains"] = int(row.count)

        for row in res_rows:
            key = (int(row.year), int(row.month))
            merged.setdefault(key, empty_month(key[0], key[1]))
            merged[key]["reservations"] = int(row.count)
            merged[key]["revenue"] = round(float(row.revenue or 0), 2)

        data = sorted(
            [
                MonthlyGrowth(
                    year=v["year"],
                    month=v["month"],
                    month_label=month_label(v["year"], v["month"]),
                    new_users=v["new_users"],
                    new_terrains=v["new_terrains"],
                    reservations=v["reservations"],
                    revenue=v["revenue"],
                )
                for v in merged.values()
            ],
            key=lambda x: (x.year, x.month),
            reverse=True,
        )

        users_growth = _growth_pct([d.new_users for d in data[:2]])
        revenue_growth = _growth_pct([d.revenue for d in data[:2]])

        return GrowthReport(
            data=data,
            users_growth_pct=users_growth,
            revenue_growth_pct=revenue_growth,
        )


# ── Helpers module-level ───────────────────────────────────────────────────────

def _terrain_from_row(row) -> AdminTerrainResponse:
    return AdminTerrainResponse(
        id=row.id,
        owner_id=row.owner_id,
        owner_name=row.owner_name,
        name=row.name,
        address=row.address,
        city=row.city,
        status=row.status,
        price_per_hour=row.price_per_hour,
        average_rating=row.average_rating,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _growth_pct(values: list) -> float | None:
    """
    Taux de croissance entre le mois le plus récent (values[0]) et le précédent (values[1]).
    Retourne None si données insuffisantes ou division par zéro.
    """
    if len(values) < 2 or values[1] == 0:
        return None
    return round((values[0] - values[1]) / values[1] * 100, 1)
