"""
Gateway Moov Money (Burkina Faso / Bénin / UEMOA).

Flux réel :
  1. Marchand POST /payment/request → obtient requestId
  2. Client compose *155*1*{montant}*{requestId}# sur son téléphone
  3. Moov envoie webhook avec reference, transactionId, transactionStatus

Implémentation actuelle : stub de développement.
"""

from app.core.config import settings
from app.models.payment import PaymentStatus
from app.services.gateways.base import AbstractPaymentGateway, InitiateResult, WebhookResult

_MOOV_STATUS_MAP = {
    "SUCCESSFUL": PaymentStatus.SUCCESS,
    "SUCCESS": PaymentStatus.SUCCESS,
    "FAILED": PaymentStatus.FAILED,
    "FAILURE": PaymentStatus.FAILED,
    "CANCELLED": PaymentStatus.FAILED,
}


class MoovMoneyGateway(AbstractPaymentGateway):

    @property
    def signature_header(self) -> str:
        return "X-Moov-Signature"

    @property
    def _webhook_secret(self) -> str:
        return settings.MOOV_MONEY_WEBHOOK_SECRET

    async def initiate(
        self,
        transaction_reference: str,
        amount: float,
        currency: str,
        player_phone: str,
        terrain_name: str,
    ) -> InitiateResult:
        """
        Stub dev — retourne un code USSD Moov simulé.
        En production : POST {MOOV_MONEY_BASE_URL}/payment/request avec API_KEY.
        """
        short_ref = transaction_reference.split("-")[-1][:6]
        ussd_code = f"*155*1*{int(amount)}*{short_ref}#"
        return InitiateResult(
            payment_url=None,
            ussd_code=ussd_code,
            provider_reference=None,
            message=(
                f"Composez {ussd_code} sur votre téléphone Moov pour payer "
                f"{amount} {currency} — {terrain_name}."
            ),
        )

    def parse_webhook(self, payload: dict) -> WebhookResult:
        """
        Format Moov Money :
        {
          "reference": "GF-MM-XXXX",
          "transactionId": "MOOV-98765",
          "transactionStatus": "SUCCESSFUL" | "FAILED",
          "amount": 1200,
          "currency": "XOF"
        }
        """
        transaction_reference = payload.get("reference", "")
        raw_status = payload.get("transactionStatus", "").upper()
        status = _MOOV_STATUS_MAP.get(raw_status, PaymentStatus.FAILED)
        return WebhookResult(
            transaction_reference=transaction_reference,
            status=status,
            provider_reference=payload.get("transactionId"),
            raw=payload,
        )
