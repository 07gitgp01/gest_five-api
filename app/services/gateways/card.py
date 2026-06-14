"""
Gateway paiement par carte bancaire (CinetPay / UEMOA).

Flux réel :
  1. Marchand POST /payment → obtient payment_url + transaction_id
  2. Client est redirigé vers payment_url pour saisir sa carte (3DS)
  3. Fournisseur envoie webhook avec transaction_id, status, authorization_code

Implémentation actuelle : stub de développement.
"""

from app.core.config import settings
from app.models.payment import PaymentStatus
from app.services.gateways.base import AbstractPaymentGateway, InitiateResult, WebhookResult

_CARD_STATUS_MAP = {
    "success": PaymentStatus.SUCCESS,
    "succeeded": PaymentStatus.SUCCESS,
    "failed": PaymentStatus.FAILED,
    "cancelled": PaymentStatus.FAILED,
    "refunded": PaymentStatus.REFUNDED,
}


class CardGateway(AbstractPaymentGateway):

    @property
    def signature_header(self) -> str:
        return "X-Card-Signature"

    @property
    def _webhook_secret(self) -> str:
        return settings.CARD_PAYMENT_WEBHOOK_SECRET

    async def initiate(
        self,
        transaction_reference: str,
        amount: float,
        currency: str,
        player_phone: str,
        terrain_name: str,
    ) -> InitiateResult:
        """
        Stub dev — retourne une URL de paiement simulée.
        En production : POST {CARD_PAYMENT_BASE_URL}/payment avec CARD_PAYMENT_API_KEY.
        """
        payment_url = (
            f"{settings.PAYMENT_SUCCESS_URL}"
            f"?ref={transaction_reference}&amount={int(amount)}&currency={currency}"
        )
        return InitiateResult(
            payment_url=payment_url,
            ussd_code=None,
            provider_reference=None,
            message=(
                f"Cliquez sur le lien pour payer {amount} {currency} "
                f"par carte — {terrain_name}."
            ),
        )

    def parse_webhook(self, payload: dict) -> WebhookResult:
        """
        Format carte (CinetPay-like) :
        {
          "transaction_id": "GF-CB-XXXX",
          "authorization_code": "AUTH-12345",
          "status": "success" | "failed" | "refunded",
          "amount": 1200,
          "currency": "XOF"
        }
        """
        transaction_reference = payload.get("transaction_id", "")
        raw_status = payload.get("status", "").lower()
        status = _CARD_STATUS_MAP.get(raw_status, PaymentStatus.FAILED)
        return WebhookResult(
            transaction_reference=transaction_reference,
            status=status,
            provider_reference=payload.get("authorization_code"),
            raw=payload,
        )
