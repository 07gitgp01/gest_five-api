import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, PaymentStatus
from app.repositories.base import BaseRepository


class PaymentRepository(BaseRepository[Payment]):
    def __init__(self, db: AsyncSession):
        super().__init__(Payment, db)

    async def get_by_transaction_ref(self, reference: str) -> Payment | None:
        result = await self.db.execute(
            select(Payment).where(Payment.transaction_reference == reference)
        )
        return result.scalar_one_or_none()

    async def get_by_reservation(self, reservation_id: uuid.UUID) -> list[Payment]:
        result = await self.db.execute(
            select(Payment)
            .where(Payment.reservation_id == reservation_id)
            .order_by(Payment.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_for_reservation(
        self, reservation_id: uuid.UUID
    ) -> Payment | None:
        """Retourne le dernier paiement PENDING ou SUCCESS pour une réservation."""
        result = await self.db.execute(
            select(Payment)
            .where(
                and_(
                    Payment.reservation_id == reservation_id,
                    Payment.status.in_([PaymentStatus.PENDING, PaymentStatus.SUCCESS]),
                )
            )
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
