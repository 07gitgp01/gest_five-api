import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, require_owner_or_admin
from app.core.logging import get_logger
from app.db.session import get_db
from app.models.user import User
from app.schemas.payment import (
    PaymentCreate,
    PaymentInitResponse,
    PaymentReceipt,
    PaymentResponse,
    RefundRequest,
    WebhookAck,
)
from app.services.payment_service import PaymentService

router = APIRouter()
logger = get_logger("gestfive.payments")


# ── Routes statiques en premier (évite la capture par /{payment_id}) ──────────

@router.post(
    "/initiate",
    response_model=PaymentInitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initier un paiement",
    description=(
        "Crée un paiement PENDING et retourne le code USSD (Orange/Moov Money) "
        "ou l'URL de redirection (carte) selon la méthode choisie."
    ),
)
async def initiate_payment(
    data: PaymentCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await PaymentService(db).initiate(current_user, data)
        logger.info(
            "PAYMENT initiated — payment_id=%s reservation_id=%s method=%s amount=%.0f",
            getattr(result, "payment_id", "?"),
            data.reservation_id,
            data.payment_method,
            getattr(result, "amount", 0),
        )
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "PAYMENT initiate erreur — reservation_id=%s method=%s user_id=%s",
            data.reservation_id,
            data.payment_method,
            current_user.id,
        )
        raise


@router.post(
    "/webhook/{provider}",
    response_model=WebhookAck,
    summary="Callback webhook fournisseur",
    description=(
        "Endpoint appelé par le fournisseur de paiement sans authentification JWT. "
        "La signature HMAC-SHA256 du payload doit être transmise dans le header "
        "approprié (X-Orange-Signature / X-Moov-Signature / X-Card-Signature). "
        "Répond toujours 200 pour les références inconnues (évite les rejeux)."
    ),
)
async def payment_webhook(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_orange_signature: str | None = Header(default=None),
    x_moov_signature: str | None = Header(default=None),
    x_card_signature: str | None = Header(default=None),
):
    # Lecture du body brut AVANT parsing JSON — indispensable pour la vérification HMAC
    payload_bytes = await request.body()

    signature_map = {
        "orange_money": x_orange_signature,
        "moov_money": x_moov_signature,
        "card": x_card_signature,
    }
    signature = signature_map.get(provider.lower())

    logger.debug(
        "WEBHOOK received — provider=%s payload=%d bytes sig=%s",
        provider,
        len(payload_bytes),
        "oui" if signature else "non",
    )

    try:
        transaction_ref = await PaymentService(db).handle_webhook(
            provider=provider,
            payload_bytes=payload_bytes,
            signature=signature,
        )
        logger.info("WEBHOOK ok — provider=%s ref=%s", provider, transaction_ref or "?")
        return WebhookAck(received=True, transaction_reference=transaction_ref)
    except Exception:
        logger.exception("WEBHOOK erreur — provider=%s", provider)
        raise


@router.get(
    "/reservation/{reservation_id}",
    response_model=list[PaymentResponse],
    summary="Paiements d'une réservation",
    description="Liste tous les paiements (PENDING, FAILED, SUCCESS) liés à une réservation.",
)
async def list_reservation_payments(
    reservation_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await PaymentService(db).list_by_reservation(current_user, reservation_id)


# ── Routes dynamiques /{payment_id} après les routes statiques ────────────────

@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    summary="Statut d'un paiement",
)
async def get_payment(
    payment_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await PaymentService(db).get_payment(current_user, payment_id)


@router.get(
    "/{payment_id}/receipt",
    response_model=PaymentReceipt,
    summary="Reçu de paiement",
    description="Disponible uniquement pour les paiements avec statut SUCCESS.",
)
async def get_receipt(
    payment_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await PaymentService(db).get_receipt(current_user, payment_id)


@router.post(
    "/{payment_id}/refund",
    response_model=PaymentResponse,
    summary="Demander un remboursement",
    description="Passe le paiement à REFUNDED et annule la réservation. Propriétaire ou admin.",
)
async def request_refund(
    payment_id: uuid.UUID,
    data: RefundRequest,
    current_user: User = Depends(require_owner_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await PaymentService(db).request_refund(current_user, payment_id, data.reason)
