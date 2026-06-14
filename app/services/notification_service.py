import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.notification import Notification, NotificationType
from app.models.reservation import Reservation
from app.models.user import User, UserRole
from app.repositories.notification_repository import NotificationRepository
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.terrain_repository import TerrainRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import Page
from app.schemas.notification import (
    BulkReadResult,
    NotificationResponse,
    ReminderResult,
    UnreadCount,
)
from app.services.fcm_service import FCMService


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NotificationRepository(db)
        self.user_repo = UserRepository(db)
        self.res_repo = ReservationRepository(db)
        self.terrain_repo = TerrainRepository(db)
        self.fcm = FCMService()

    # ── Cœur : créer + envoyer ─────────────────────────────────────────────────

    async def notify(
        self,
        user_id: uuid.UUID,
        type: NotificationType,
        title: str,
        body: str,
        data: dict | None = None,
        reservation_id: uuid.UUID | None = None,
        payment_id: uuid.UUID | None = None,
    ) -> Notification:
        """
        Crée une notification en base, puis tente un envoi FCM (best-effort).
        N'émet jamais d'exception sur l'étape FCM.
        """
        notification = await self.repo.create(
            {
                "user_id": user_id,
                "type": type,
                "title": title,
                "body": body,
                "data": data,
                "reservation_id": reservation_id,
                "payment_id": payment_id,
            }
        )
        user = await self.user_repo.get(user_id)
        if user and user.fcm_token:
            await self.fcm.send(
                token=user.fcm_token,
                title=title,
                body=body,
                data=data or {},
                notification_type=type.value,
            )
        return notification

    # ── Déclencheurs métier ────────────────────────────────────────────────────

    async def on_payment_success(
        self, reservation_id: uuid.UUID, payment_id: uuid.UUID
    ) -> None:
        """Déclenché par le webhook de paiement SUCCESS."""
        reservation = await self.res_repo.get(reservation_id)
        if not reservation:
            return
        terrain = await self.terrain_repo.get(reservation.terrain_id)
        terrain_name = terrain.name if terrain else "votre terrain"
        start_str = reservation.start_datetime.strftime("%d/%m à %H:%M")

        await self.notify(
            user_id=reservation.player_id,
            type=NotificationType.PAYMENT_SUCCESS,
            title="Paiement réussi ✓",
            body="Votre paiement a été confirmé.",
            reservation_id=reservation_id,
            payment_id=payment_id,
        )
        await self.notify(
            user_id=reservation.player_id,
            type=NotificationType.RESERVATION_CONFIRMED,
            title="Réservation confirmée",
            body=f"Votre terrain {terrain_name} est réservé pour le {start_str}.",
            data={"terrain_name": terrain_name, "start": start_str},
            reservation_id=reservation_id,
        )

    async def on_cancellation(self, reservation: Reservation) -> None:
        """Déclenché par l'annulation d'une réservation (joueur ou admin)."""
        terrain = await self.terrain_repo.get(reservation.terrain_id)
        terrain_name = terrain.name if terrain else "votre terrain"
        start_str = reservation.start_datetime.strftime("%d/%m à %H:%M")

        await self.notify(
            user_id=reservation.player_id,
            type=NotificationType.CANCELLATION,
            title="Réservation annulée",
            body=f"Votre réservation du {start_str} sur {terrain_name} a été annulée.",
            reservation_id=reservation.id,
        )

    # ── Rappels de match ───────────────────────────────────────────────────────

    async def send_match_reminders(self) -> ReminderResult:
        """
        Envoie les rappels pour les réservations CONFIRMED qui commencent
        dans les 30–90 prochaines minutes.
        Idempotent : une seule notification MATCH_REMINDER par réservation.
        Prévu pour être appelé par un cron job ou une tâche planifiée.
        """
        now = datetime.now(timezone.utc)
        window_start = now + timedelta(minutes=30)
        window_end = now + timedelta(minutes=90)

        reservations = await self.res_repo.get_upcoming_for_reminder(
            window_start, window_end
        )
        sent = 0
        for reservation in reservations:
            if await self.repo.reminder_already_sent(reservation.id):
                continue
            terrain = await self.terrain_repo.get(reservation.terrain_id)
            terrain_name = terrain.name if terrain else "votre terrain"
            start_str = reservation.start_datetime.strftime("%H:%M")

            await self.notify(
                user_id=reservation.player_id,
                type=NotificationType.MATCH_REMINDER,
                title="Rappel : match dans moins d'1 heure !",
                body=(
                    f"Votre match sur {terrain_name} commence à {start_str}. "
                    "Préparez-vous !"
                ),
                data={"terrain_name": terrain_name, "start_time": start_str},
                reservation_id=reservation.id,
            )
            sent += 1

        return ReminderResult(
            sent=sent,
            message=(
                f"{sent} rappel(s) envoyé(s)."
                if sent else "Aucun rappel à envoyer pour cette fenêtre."
            ),
        )

    # ── Endpoints utilisateur ──────────────────────────────────────────────────

    async def list_my(
        self,
        user: User,
        skip: int,
        limit: int,
        unread_only: bool = False,
    ) -> Page[NotificationResponse]:
        items, total = await self.repo.get_by_user(
            user.id, skip=skip, limit=limit, unread_only=unread_only
        )
        return Page.build(
            items=[NotificationResponse.model_validate(n) for n in items],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get_unread_count(self, user: User) -> UnreadCount:
        count = await self.repo.count_unread(user.id)
        return UnreadCount(count=count)

    async def mark_read(self, user: User, notification_id: uuid.UUID) -> NotificationResponse:
        notification = await self.repo.get(notification_id)
        if not notification:
            raise NotFoundException("Notification introuvable")
        if notification.user_id != user.id:
            raise ForbiddenException()
        updated = await self.repo.mark_read(notification)
        return NotificationResponse.model_validate(updated)

    async def mark_all_read(self, user: User) -> BulkReadResult:
        updated = await self.repo.mark_all_read(user.id)
        return BulkReadResult(updated=updated)

    async def delete(self, user: User, notification_id: uuid.UUID) -> None:
        notification = await self.repo.get(notification_id)
        if not notification:
            raise NotFoundException("Notification introuvable")
        if notification.user_id != user.id and user.role != UserRole.ADMIN:
            raise ForbiddenException()
        await self.repo.delete(notification)

    async def register_fcm_token(self, user: User, token: str) -> None:
        """Enregistre ou met à jour le token FCM du périphérique de l'utilisateur."""
        await self.user_repo.update(user, {"fcm_token": token})
