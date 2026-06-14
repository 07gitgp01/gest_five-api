import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, select, update

from app.models.notification import Notification, NotificationType
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    def __init__(self, db):
        super().__init__(Notification, db)

    async def get_by_user(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
        unread_only: bool = False,
    ) -> tuple[list[Notification], int]:
        filters = [Notification.user_id == user_id]
        if unread_only:
            filters.append(Notification.is_read == False)  # noqa: E712

        where = and_(*filters)

        total = (
            await self.db.execute(
                select(func.count(Notification.id)).where(where)
            )
        ).scalar_one()

        items = list(
            (
                await self.db.execute(
                    select(Notification)
                    .where(where)
                    .order_by(Notification.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return items, total

    async def count_unread(self, user_id: uuid.UUID) -> int:
        q = select(func.count(Notification.id)).where(
            and_(
                Notification.user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
        )
        return (await self.db.execute(q)).scalar_one()

    async def mark_read(self, notification: Notification) -> Notification:
        return await self.update(
            notification,
            {"is_read": True, "read_at": datetime.now(timezone.utc)},
        )

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        """Mise à jour en lot — une seule requête UPDATE. Retourne le nombre affecté."""
        count = await self.count_unread(user_id)
        if count == 0:
            return 0
        await self.db.execute(
            update(Notification)
            .where(
                and_(
                    Notification.user_id == user_id,
                    Notification.is_read == False,  # noqa: E712
                )
            )
            .values(is_read=True, read_at=datetime.now(timezone.utc))
        )
        await self.db.flush()
        return count

    async def reminder_already_sent(self, reservation_id: uuid.UUID) -> bool:
        """
        Idempotence pour les rappels : évite d'envoyer deux fois
        un MATCH_REMINDER pour la même réservation.
        """
        q = (
            select(Notification.id)
            .where(
                and_(
                    Notification.reservation_id == reservation_id,
                    Notification.type == NotificationType.MATCH_REMINDER,
                )
            )
            .limit(1)
        )
        return (await self.db.execute(q)).scalar_one_or_none() is not None
