"""
Service de paiement GestFive.

Orchestration :
  initiate()       → crée Payment(PENDING) + appelle gateway
  handle_webhook() → met à jour Payment + Reservation si SUCCESS
  get_receipt()    → construit le reçu (SUCCESS uniquement)
  request_refund() → passe Payment à REFUNDED + Reservation à CANCELLED

Idempotence webhook :
  Si le payment possède déjà le statut reçu, on retourne immédiatement sans
  réécriture ni double-envoi de notification.

Savepoints notifications :
  Les appels à NotificationService s'exécutent dans un savepoint (begin_nested).
  Une erreur dans la notification rollbacke uniquement le savepoint ; la mise
  à jour du payment reste valide et sera commitée par get_db().
"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.reservation import Reservation, ReservationStatus
from app.models.user import User, UserRole
from app.repositories.payment_repository import PaymentRepository
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.terrain_repository import TerrainRepository
from app.repositories.user_repository import UserRepository
from app.schemas.payment import (
    PaymentCreate,
    PaymentInitResponse,
    PaymentReceipt,
    PaymentResponse,
)
from app.services.gateways import get_gateway, get_gateway_by_provider


def _generate_transaction_ref(method: PaymentMethod) -> str:
    prefix = {
        PaymentMethod.ORANGE_MONEY: "OM",
        PaymentMethod.MOOV_MONEY: "MM",
        PaymentMethod.CARD: "CB",
    }[method]
    return f"GF-{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _generate_receipt_number(payment_id: uuid.UUID) -> str:
    short = str(payment_id).replace("-", "")[:8].upper()
    return f"REC-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{short}"


class PaymentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PaymentRepository(db)
        self.res_repo = ReservationRepository(db)
        self.terrain_repo = TerrainRepository(db)
        self.user_repo = UserRepository(db)

    # ── Initiation ────────────────────────────────────────────────────────────

    async def initiate(self, player: User, data: PaymentCreate) -> PaymentInitResponse:
        reservation = await self._get_reservation_for_player(player, data.reservation_id)

        if reservation.status == ReservationStatus.CANCELLED:
            raise BadRequestException("Impossible de payer une réservation annulée")
        if reservation.status == ReservationStatus.COMPLETED:
            raise BadRequestException("Cette réservation est déjà terminée")

        existing = await self.repo.get_active_for_reservation(data.reservation_id)
        if existing:
            if existing.status == PaymentStatus.SUCCESS:
                raise BadRequestException("Cette réservation est déjà payée")
            if existing.status == PaymentStatus.PENDING:
                raise BadRequestException(
                    "Un paiement est déjà en cours. "
                    f"Référence : {existing.transaction_reference}"
                )

        terrain = await self.terrain_repo.get(reservation.terrain_id)
        if not terrain:
            raise NotFoundException("Terrain introuvable")

        transaction_ref = _generate_transaction_ref(data.payment_method)

        payment = await self.repo.create({
            "reservation_id": data.reservation_id,
            "amount": reservation.total_price,
            "currency": settings.PAYMENT_CURRENCY,
            "payment_method": data.payment_method,
            "transaction_reference": transaction_ref,
            "status": PaymentStatus.PENDING,
        })

        gateway = get_gateway(data.payment_method)
        result = await gateway.initiate(
            transaction_reference=transaction_ref,
            amount=reservation.total_price,
            currency=settings.PAYMENT_CURRENCY,
            player_phone=player.phone,
            terrain_name=terrain.name,
        )

        return PaymentInitResponse(
            payment_id=payment.id,
            transaction_reference=transaction_ref,
            amount=reservation.total_price,
            currency=settings.PAYMENT_CURRENCY,
            payment_method=data.payment_method,
            status=PaymentStatus.PENDING,
            ussd_code=result.ussd_code,
            payment_url=result.payment_url,
            message=result.message,
        )

    # ── Webhook ───────────────────────────────────────────────────────────────

    async def handle_webhook(
        self,
        provider: str,
        payload_bytes: bytes,
        signature: str | None,
    ) -> str:
        """
        Reçoit et traite le callback d'un fournisseur de paiement.
        Retourne la transaction_reference traitée.
        """
        try:
            gateway = get_gateway_by_provider(provider)
        except ValueError as exc:
            raise BadRequestException(str(exc))

        if not gateway.verify_signature(payload_bytes, signature):
            raise BadRequestException(
                f"Signature webhook invalide pour le fournisseur : {provider}"
            )

        try:
            payload = json.loads(payload_bytes)
        except json.JSONDecodeError:
            raise BadRequestException("Payload webhook invalide (JSON attendu)")

        result = gateway.parse_webhook(payload)

        payment = await self.repo.get_by_transaction_ref(result.transaction_reference)
        if not payment:
            # Référence inconnue — on répond 200 quand même pour ne pas retriggerer
            return result.transaction_reference

        # Idempotence : si le payment est déjà dans cet état, on ne retraite pas
        if payment.status == result.status:
            return result.transaction_reference

        update_data: dict = {
            "status": result.status,
            "provider_data": result.raw,
        }
        if result.provider_reference:
            update_data["provider_reference"] = result.provider_reference

        if result.status == PaymentStatus.SUCCESS:
            update_data["paid_at"] = datetime.now(timezone.utc)
            await self._confirm_reservation(payment.reservation_id)
            # Notification dans un savepoint — un échec ici n'affecte pas la mise
            # à jour du payment (pas de session poisoning).
            try:
                from app.services.notification_service import NotificationService
                async with self.db.begin_nested():
                    await NotificationService(self.db).on_payment_success(
                        payment.reservation_id, payment.id
                    )
            except Exception:
                pass

        elif result.status == PaymentStatus.FAILED:
            update_data["failure_reason"] = payload.get("message") or "Paiement refusé"

        elif result.status == PaymentStatus.REFUNDED:
            await self._cancel_reservation(payment.reservation_id)

        await self.repo.update(payment, update_data)
        return result.transaction_reference

    async def _confirm_reservation(self, reservation_id: uuid.UUID) -> None:
        reservation = await self.res_repo.get(reservation_id)
        if reservation and reservation.status == ReservationStatus.PENDING:
            await self.res_repo.update(reservation, {"status": ReservationStatus.CONFIRMED})

    async def _cancel_reservation(self, reservation_id: uuid.UUID) -> None:
        reservation = await self.res_repo.get(reservation_id)
        if reservation and reservation.status in (
            ReservationStatus.PENDING, ReservationStatus.CONFIRMED
        ):
            await self.res_repo.update(reservation, {"status": ReservationStatus.CANCELLED})

    # ── Lecture ───────────────────────────────────────────────────────────────

    async def get_payment(self, user: User, payment_id: uuid.UUID) -> PaymentResponse:
        payment = await self._get_payment_or_raise(payment_id)
        await self._check_access(user, payment)
        return PaymentResponse.model_validate(payment)

    async def list_by_reservation(
        self, user: User, reservation_id: uuid.UUID
    ) -> list[PaymentResponse]:
        reservation = await self.res_repo.get(reservation_id)
        if not reservation:
            raise NotFoundException("Réservation introuvable")

        await self._check_reservation_access(user, reservation)

        payments = await self.repo.get_by_reservation(reservation_id)
        return [PaymentResponse.model_validate(p) for p in payments]

    async def get_receipt(self, user: User, payment_id: uuid.UUID) -> PaymentReceipt:
        payment = await self._get_payment_or_raise(payment_id)
        await self._check_access(user, payment)

        if payment.status != PaymentStatus.SUCCESS:
            raise BadRequestException(
                "Le reçu n'est disponible que pour les paiements réussis "
                f"(statut actuel : {payment.status})"
            )

        reservation = await self.res_repo.get(payment.reservation_id)
        terrain = await self.terrain_repo.get(reservation.terrain_id)
        player = await self.user_repo.get(reservation.player_id)

        duration_min = int(
            (reservation.end_datetime - reservation.start_datetime).total_seconds() / 60
        )

        return PaymentReceipt(
            receipt_number=_generate_receipt_number(payment.id),
            payment_id=payment.id,
            reservation_id=reservation.id,
            player_name=f"{player.firstname} {player.lastname}",
            player_phone=player.phone,
            terrain_name=terrain.name,
            terrain_city=terrain.city,
            start_datetime=reservation.start_datetime,
            end_datetime=reservation.end_datetime,
            duration_minutes=duration_min,
            amount=payment.amount,
            currency=payment.currency,
            payment_method=payment.payment_method,
            transaction_reference=payment.transaction_reference,
            provider_reference=payment.provider_reference,
            status=payment.status,
            paid_at=payment.paid_at,
            issued_at=datetime.now(timezone.utc),
        )

    # ── Remboursement ─────────────────────────────────────────────────────────

    async def request_refund(
        self, user: User, payment_id: uuid.UUID, reason: str = ""
    ) -> PaymentResponse:
        """
        Marque le paiement REFUNDED et annule la réservation associée.
        Réservé au propriétaire du terrain ou à un admin.
        """
        payment = await self._get_payment_or_raise(payment_id)
        reservation = await self.res_repo.get(payment.reservation_id)
        terrain = await self.terrain_repo.get(reservation.terrain_id)

        if user.role != UserRole.ADMIN and terrain.owner_id != user.id:
            raise ForbiddenException("Seul le propriétaire du terrain ou un admin peut rembourser")

        if payment.status != PaymentStatus.SUCCESS:
            raise BadRequestException(
                f"Seuls les paiements SUCCESS peuvent être remboursés (statut : {payment.status})"
            )

        updated = await self.repo.update(payment, {
            "status": PaymentStatus.REFUNDED,
            "failure_reason": reason or "Remboursement demandé",
        })
        await self._cancel_reservation(payment.reservation_id)
        return PaymentResponse.model_validate(updated)

    # ── Helpers privés ────────────────────────────────────────────────────────

    async def _get_payment_or_raise(self, payment_id: uuid.UUID) -> Payment:
        payment = await self.repo.get(payment_id)
        if not payment:
            raise NotFoundException("Paiement introuvable")
        return payment

    async def _get_reservation_for_player(
        self, player: User, reservation_id: uuid.UUID
    ) -> Reservation:
        reservation = await self.res_repo.get(reservation_id)
        if not reservation:
            raise NotFoundException("Réservation introuvable")
        if reservation.player_id != player.id:
            raise ForbiddenException("Cette réservation ne vous appartient pas")
        return reservation

    async def _check_access(self, user: User, payment: Payment) -> None:
        """Player, propriétaire du terrain ou admin peuvent voir un paiement."""
        if user.role == UserRole.ADMIN:
            return
        reservation = await self.res_repo.get(payment.reservation_id)
        if not reservation:
            raise NotFoundException("Réservation introuvable")
        if reservation.player_id == user.id:
            return
        terrain = await self.terrain_repo.get(reservation.terrain_id)
        if terrain and terrain.owner_id == user.id:
            return
        raise ForbiddenException()

    async def _check_reservation_access(
        self, user: User, reservation: Reservation
    ) -> None:
        if user.role == UserRole.ADMIN or reservation.player_id == user.id:
            return
        terrain = await self.terrain_repo.get(reservation.terrain_id)
        if terrain and terrain.owner_id == user.id:
            return
        raise ForbiddenException()
