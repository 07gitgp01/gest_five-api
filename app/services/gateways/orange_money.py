"""
Gateway Orange Money (Burkina Faso / UEMOA).

Flux réel :
  1. Marchand POST /webpayment → obtient payment_token
  2. Client compose *144*4*6*{montant}*{token}# sur son téléphone
  3. Orange envoie webhook POST avec notifToken, txnid, status

Implémentation actuelle : stub de développement (pas d'appel HTTP réel).
Pour la production, remplacer `initiate` par un appel à ORANGE_MONEY_BASE_URL.
"""

from app.core.config import settings
from app.models.payment import PaymentStatus
from app.services.gateways.base import AbstractPaymentGateway, InitiateResult, WebhookResult


class OrangeMoneyGateway(AbstractPaymentGateway):

    @property
    def signature_header(self) -> str:
        return "X-Orange-Signature"

    @property
    def _webhook_secret(self) -> str:
        return settings.ORANGE_MONEY_WEBHOOK_SECRET

    async def initiate(
        self,
        transaction_reference: str,
        amount: float,
        currency: str,
        player_phone: str,
        terrain_name: str,
    ) -> InitiateResult:
        """
        Stub dev — retourne un code USSD simulé.
        En production : POST {ORANGE_MONEY_BASE_URL}/webpayment avec MERCHANT_KEY.
        """
        short_ref = transaction_reference.split("-")[-1][:6]
        ussd_code = f"*144*4*6*{int(amount)}*{short_ref}#"
        return InitiateResult(
            payment_url=None,
            ussd_code=ussd_code,
            provider_reference=None,
            message=(
                f"Composez {ussd_code} sur votre téléphone Orange pour payer "
                f"{amount} {currency} — {terrain_name}."
            ),
        )

    def parse_webhook(self, payload: dict) -> WebhookResult:
        """
        Format Orange Money :
        {
          "notifToken": "...",
          "txnid": "GF-OM-XXXX",
          "status": "SUCCESS" | "FAILED",
          "amount": "1200",
          "currency": "XOF",
          "msisdn": "+22670000001"
        }
        """
        transaction_reference = payload.get("txnid", "")
        raw_status = payload.get("status", "").upper()
        status = (
            PaymentStatus.SUCCESS if raw_status == "SUCCESS"
            else PaymentStatus.FAILED
        )
        return WebhookResult(
            transaction_reference=transaction_reference,
            status=status,
            provider_reference=payload.get("notifToken"),
            raw=payload,
        )
