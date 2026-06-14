"""
Contrat abstrait pour les gateways de paiement GestFive.

Chaque fournisseur implémente :
  - initiate()          → démarre le paiement côté fournisseur
  - verify_signature()  → valide la signature HMAC du webhook entrant
  - parse_webhook()     → normalise le payload fournisseur en données GestFive
  - signature_header    → nom du header HTTP portant la signature
"""

import hashlib
import hmac
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.payment import PaymentStatus


@dataclass
class InitiateResult:
    """Résultat de l'initiation d'un paiement."""

    payment_url: str | None   # Carte → URL de redirection 3DS
    ussd_code: str | None     # Mobile money → code à composer (*XXX#)
    provider_reference: str | None  # ID fournisseur assigné à l'initiation
    message: str              # Message lisible pour le joueur


@dataclass
class WebhookResult:
    """Données normalisées extraites d'un webhook fournisseur."""

    transaction_reference: str   # Référence GestFive (GF-XX-XXXX)
    status: PaymentStatus
    provider_reference: str | None
    raw: dict                    # Payload original pour stockage


class AbstractPaymentGateway(ABC):

    @property
    @abstractmethod
    def signature_header(self) -> str:
        """Nom du header HTTP portant la signature HMAC."""
        ...

    @property
    @abstractmethod
    def _webhook_secret(self) -> str:
        """Secret partagé avec le fournisseur pour la vérification HMAC."""
        ...

    @abstractmethod
    async def initiate(
        self,
        transaction_reference: str,
        amount: float,
        currency: str,
        player_phone: str,
        terrain_name: str,
    ) -> InitiateResult:
        """Initie un paiement auprès du fournisseur."""
        ...

    @abstractmethod
    def parse_webhook(self, payload: dict) -> WebhookResult:
        """Convertit le payload brut du fournisseur en WebhookResult normalisé."""
        ...

    def verify_signature(self, payload_bytes: bytes, signature: str | None) -> bool:
        """
        Vérifie la signature HMAC-SHA256 du webhook.

        Tous les fournisseurs utilisent HMAC-SHA256(secret, body).
        La comparaison est time-constant pour prévenir les timing attacks.
        """
        if not signature:
            return False
        expected = hmac.new(
            self._webhook_secret.encode(),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature.lower())
