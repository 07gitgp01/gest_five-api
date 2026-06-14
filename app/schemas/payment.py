import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.payment import PaymentMethod, PaymentStatus


# ── Entrée ─────────────────────────────────────────────────────────────────────

class PaymentCreate(BaseModel):
    reservation_id: uuid.UUID
    payment_method: PaymentMethod


class RefundRequest(BaseModel):
    reason: str = Field(default="", description="Motif du remboursement")


# ── Sortie ─────────────────────────────────────────────────────────────────────

class PaymentResponse(BaseModel):
    id: uuid.UUID
    reservation_id: uuid.UUID
    amount: float
    currency: str
    payment_method: PaymentMethod
    transaction_reference: str
    provider_reference: str | None
    status: PaymentStatus
    paid_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaymentInitResponse(BaseModel):
    """Réponse à l'initiation d'un paiement — contient les instructions pour le joueur."""

    payment_id: uuid.UUID
    transaction_reference: str
    amount: float
    currency: str
    payment_method: PaymentMethod
    status: PaymentStatus
    # Mobile money → code USSD à composer ; carte → URL de redirection
    ussd_code: str | None = None
    payment_url: str | None = None
    message: str


# ── Webhook ────────────────────────────────────────────────────────────────────

class WebhookAck(BaseModel):
    """Corps de réponse renvoyé au fournisseur pour accuser réception."""

    received: bool = True
    transaction_reference: str


# ── Reçu ───────────────────────────────────────────────────────────────────────

class PaymentReceipt(BaseModel):
    """Reçu de paiement complet — disponible uniquement si statut SUCCESS."""

    receipt_number: str
    payment_id: uuid.UUID
    reservation_id: uuid.UUID
    # Joueur
    player_name: str
    player_phone: str
    # Terrain
    terrain_name: str
    terrain_city: str
    # Créneau
    start_datetime: datetime
    end_datetime: datetime
    duration_minutes: int
    # Paiement
    amount: float
    currency: str
    payment_method: PaymentMethod
    transaction_reference: str
    provider_reference: str | None
    status: PaymentStatus
    paid_at: datetime
    issued_at: datetime
