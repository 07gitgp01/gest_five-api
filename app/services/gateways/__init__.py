from app.models.payment import PaymentMethod
from app.services.gateways.base import AbstractPaymentGateway
from app.services.gateways.card import CardGateway
from app.services.gateways.moov_money import MoovMoneyGateway
from app.services.gateways.orange_money import OrangeMoneyGateway


def get_gateway(method: PaymentMethod) -> AbstractPaymentGateway:
    """Retourne le gateway correspondant à la méthode de paiement."""
    return {
        PaymentMethod.ORANGE_MONEY: OrangeMoneyGateway,
        PaymentMethod.MOOV_MONEY: MoovMoneyGateway,
        PaymentMethod.CARD: CardGateway,
    }[method]()


def get_gateway_by_provider(provider: str) -> AbstractPaymentGateway:
    """Retourne le gateway à partir du nom de fournisseur (utilisé dans les webhooks)."""
    mapping: dict[str, type[AbstractPaymentGateway]] = {
        "orange_money": OrangeMoneyGateway,
        "moov_money": MoovMoneyGateway,
        "card": CardGateway,
    }
    cls = mapping.get(provider.lower())
    if cls is None:
        raise ValueError(f"Fournisseur de paiement inconnu : {provider}")
    return cls()


__all__ = [
    "AbstractPaymentGateway",
    "get_gateway",
    "get_gateway_by_provider",
]
