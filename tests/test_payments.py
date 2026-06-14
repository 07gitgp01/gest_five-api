"""
Tests du module Paiement GestFive.

Flux testé :
  1. Joueur initie un paiement → reçoit USSD / URL
  2. Fournisseur envoie webhook SUCCESS → Payment=SUCCESS, Reservation=CONFIRMED
  3. Joueur consulte le statut et récupère le reçu
  4. Propriétaire demande un remboursement → Payment=REFUNDED, Reservation=CANCELLED

Autres cas :
  - Webhook FAILED → Payment=FAILED, Reservation reste PENDING
  - Double paiement → 400
  - Paiement d'une réservation annulée → 400
  - Reçu sur paiement non-SUCCESS → 400
  - Accès non autorisé au paiement → 403
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.config import settings

# ── Helpers partagés ──────────────────────────────────────────────────────────

OWNER = {"firstname": "Kofi", "lastname": "Mensah", "phone": "+22672000001",
         "password": "owner1234", "role": "owner"}
CLIENT_A = {"firstname": "Adja", "lastname": "Diallo", "phone": "+22672000002",
            "password": "client1234", "role": "client"}
CLIENT_B = {"firstname": "Seydou", "lastname": "Traoré", "phone": "+22672000003",
            "password": "client1234", "role": "client"}

OPENING = {
    "monday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "tuesday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "wednesday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "thursday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "friday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "saturday": {"open": "09:00", "close": "20:00", "is_closed": False},
    "sunday": {"open": "00:00", "close": "00:00", "is_closed": True},
}

TERRAIN_BODY = {"name": "Terrain Gamma", "address": "Zone C", "city": "Bobo-Dioulasso",
                "price_per_hour": 15.0, "opening_hours": OPENING}


async def _tok(client: AsyncClient, payload: dict) -> str:
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.json()
    return r.json()["access_token"]


async def _terrain(client: AsyncClient, token: str) -> dict:
    r = await client.post("/api/v1/terrains/", json=TERRAIN_BODY,
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.json()
    return r.json()


def _next_monday(hour: int = 10, duration_h: int = 1) -> dict:
    now = datetime.now(timezone.utc)
    days = (7 - now.weekday()) % 7 or 7
    start = (now + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return {
        "start_datetime": start.isoformat(),
        "end_datetime": (start + timedelta(hours=duration_h)).isoformat(),
    }


async def _slot(client: AsyncClient, tok: str, terrain_id: str, hour: int = 10) -> dict:
    r = await client.post(f"/api/v1/terrains/{terrain_id}/slots", json=_next_monday(hour=hour),
                          headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 201, r.json()
    return r.json()


async def _reservation(client: AsyncClient, tok: str, slot_id: str) -> dict:
    r = await client.post("/api/v1/reservations/", json={"time_slot_id": slot_id},
                          headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 201, r.json()
    return r.json()


def _sign(secret: str, payload: dict) -> str:
    """Génère la signature HMAC-SHA256 comme le fait le fournisseur de paiement."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _om_webhook(transaction_reference: str, status: str = "SUCCESS") -> tuple[dict, str]:
    """Construit le payload + signature Orange Money."""
    payload = {
        "notifToken": "notif-token-xyz",
        "txnid": transaction_reference,
        "status": status,
        "amount": "1500",
        "currency": "XOF",
        "msisdn": "+22670000001",
    }
    sig = _sign(settings.ORANGE_MONEY_WEBHOOK_SECRET, payload)
    return payload, sig


def _mm_webhook(transaction_reference: str, status: str = "SUCCESSFUL") -> tuple[dict, str]:
    """Construit le payload + signature Moov Money."""
    payload = {
        "reference": transaction_reference,
        "transactionId": "MOOV-12345",
        "transactionStatus": status,
        "amount": 1500,
        "currency": "XOF",
    }
    sig = _sign(settings.MOOV_MONEY_WEBHOOK_SECRET, payload)
    return payload, sig


def _card_webhook(transaction_reference: str, status: str = "success") -> tuple[dict, str]:
    """Construit le payload + signature carte."""
    payload = {
        "transaction_id": transaction_reference,
        "authorization_code": "AUTH-99999",
        "status": status,
        "amount": 1500,
        "currency": "XOF",
    }
    sig = _sign(settings.CARD_PAYMENT_WEBHOOK_SECRET, payload)
    return payload, sig


# ── Utilitaire : scénario complet jusqu'à l'initiation ───────────────────────

async def _setup_payment(
    client: AsyncClient,
    owner_phone: str,
    client_phone: str,
    method: str = "orange_money",
    hour: int = 10,
) -> tuple[str, str, str, str]:
    """
    Crée owner, client, terrain, slot, réservation et initie un paiement.
    Retourne (owner_tok, client_tok, reservation_id, transaction_reference).
    """
    owner_tok = await _tok(client, {**OWNER, "phone": owner_phone})
    client_tok = await _tok(client, {**CLIENT_A, "phone": client_phone})
    terrain_data = await _terrain(client, owner_tok)
    slot_data = await _slot(client, owner_tok, terrain_data["id"], hour=hour)
    res_data = await _reservation(client, client_tok, slot_data["id"])

    init_resp = await client.post(
        "/api/v1/payments/initiate",
        json={"reservation_id": res_data["id"], "payment_method": method},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert init_resp.status_code == 201, init_resp.json()
    tx_ref = init_resp.json()["transaction_reference"]
    return owner_tok, client_tok, res_data["id"], tx_ref


# ── Initiation ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_initiate_orange_money(client: AsyncClient):
    owner_tok = await _tok(client, {**OWNER, "phone": "+22672010001"})
    client_tok = await _tok(client, {**CLIENT_A, "phone": "+22672010002"})
    terrain_data = await _terrain(client, owner_tok)
    slot_data = await _slot(client, owner_tok, terrain_data["id"], hour=10)
    res = await _reservation(client, client_tok, slot_data["id"])

    resp = await client.post(
        "/api/v1/payments/initiate",
        json={"reservation_id": res["id"], "payment_method": "orange_money"},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["payment_method"] == "orange_money"
    assert data["ussd_code"] is not None
    assert data["ussd_code"].startswith("*144")
    assert data["payment_url"] is None
    assert data["transaction_reference"].startswith("GF-OM-")
    assert data["amount"] == 15.0


@pytest.mark.asyncio
async def test_initiate_moov_money(client: AsyncClient):
    owner_tok = await _tok(client, {**OWNER, "phone": "+22672010003"})
    client_tok = await _tok(client, {**CLIENT_A, "phone": "+22672010004"})
    terrain_data = await _terrain(client, owner_tok)
    slot_data = await _slot(client, owner_tok, terrain_data["id"], hour=11)
    res = await _reservation(client, client_tok, slot_data["id"])

    resp = await client.post(
        "/api/v1/payments/initiate",
        json={"reservation_id": res["id"], "payment_method": "moov_money"},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["ussd_code"].startswith("*155")
    assert data["transaction_reference"].startswith("GF-MM-")


@pytest.mark.asyncio
async def test_initiate_card(client: AsyncClient):
    owner_tok = await _tok(client, {**OWNER, "phone": "+22672010005"})
    client_tok = await _tok(client, {**CLIENT_A, "phone": "+22672010006"})
    terrain_data = await _terrain(client, owner_tok)
    slot_data = await _slot(client, owner_tok, terrain_data["id"], hour=12)
    res = await _reservation(client, client_tok, slot_data["id"])

    resp = await client.post(
        "/api/v1/payments/initiate",
        json={"reservation_id": res["id"], "payment_method": "card"},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["payment_url"] is not None
    assert data["ussd_code"] is None
    assert data["transaction_reference"].startswith("GF-CB-")


@pytest.mark.asyncio
async def test_cannot_pay_cancelled_reservation(client: AsyncClient):
    owner_tok = await _tok(client, {**OWNER, "phone": "+22672010007"})
    client_tok = await _tok(client, {**CLIENT_A, "phone": "+22672010008"})
    terrain_data = await _terrain(client, owner_tok)
    slot_data = await _slot(client, owner_tok, terrain_data["id"], hour=13)
    res = await _reservation(client, client_tok, slot_data["id"])

    # Annuler la réservation
    await client.patch(
        f"/api/v1/reservations/{res['id']}/cancel",
        headers={"Authorization": f"Bearer {client_tok}"},
    )

    resp = await client.post(
        "/api/v1/payments/initiate",
        json={"reservation_id": res["id"], "payment_method": "orange_money"},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_cannot_pay_other_player_reservation(client: AsyncClient):
    owner_tok = await _tok(client, {**OWNER, "phone": "+22672010009"})
    tok_a = await _tok(client, {**CLIENT_A, "phone": "+22672010010"})
    tok_b = await _tok(client, {**CLIENT_B, "phone": "+22672010011"})
    terrain_data = await _terrain(client, owner_tok)
    slot_data = await _slot(client, owner_tok, terrain_data["id"], hour=14)
    res = await _reservation(client, tok_a, slot_data["id"])

    resp = await client.post(
        "/api/v1/payments/initiate",
        json={"reservation_id": res["id"], "payment_method": "orange_money"},
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_double_payment_pending_rejected(client: AsyncClient):
    owner_tok = await _tok(client, {**OWNER, "phone": "+22672010012"})
    client_tok = await _tok(client, {**CLIENT_A, "phone": "+22672010013"})
    terrain_data = await _terrain(client, owner_tok)
    slot_data = await _slot(client, owner_tok, terrain_data["id"], hour=15)
    res = await _reservation(client, client_tok, slot_data["id"])

    body = {"reservation_id": res["id"], "payment_method": "orange_money"}
    r1 = await client.post(
        "/api/v1/payments/initiate", json=body,
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/api/v1/payments/initiate", json=body,
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert r2.status_code == 400
    assert "en cours" in r2.json()["detail"].lower()


# ── Webhook ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orange_money_webhook_success(client: AsyncClient):
    _, client_tok, res_id, tx_ref = await _setup_payment(
        client, "+22672020001", "+22672020002", method="orange_money", hour=10
    )

    payload, sig = _om_webhook(tx_ref, "SUCCESS")
    resp = await client.post(
        "/api/v1/payments/webhook/orange_money",
        content=json.dumps(payload, separators=(",", ":")),
        headers={"Content-Type": "application/json", "X-Orange-Signature": sig},
    )
    assert resp.status_code == 200
    assert resp.json()["received"] is True

    # Paiement → SUCCESS
    payment_resp = await client.get(
        f"/api/v1/payments/reservation/{res_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert payment_resp.status_code == 200
    payments = payment_resp.json()
    assert len(payments) == 1
    assert payments[0]["status"] == "success"
    assert payments[0]["provider_reference"] == "notif-token-xyz"

    # Réservation → CONFIRMED
    res_detail = await client.get(
        f"/api/v1/reservations/mine/{res_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert res_detail.json()["status"] == "confirmed"


@pytest.mark.asyncio
async def test_moov_money_webhook_success(client: AsyncClient):
    _, client_tok, res_id, tx_ref = await _setup_payment(
        client, "+22672020003", "+22672020004", method="moov_money", hour=11
    )

    payload, sig = _mm_webhook(tx_ref, "SUCCESSFUL")
    resp = await client.post(
        "/api/v1/payments/webhook/moov_money",
        content=json.dumps(payload, separators=(",", ":")),
        headers={"Content-Type": "application/json", "X-Moov-Signature": sig},
    )
    assert resp.status_code == 200

    payment_list = await client.get(
        f"/api/v1/payments/reservation/{res_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert payment_list.json()[0]["status"] == "success"
    assert payment_list.json()[0]["provider_reference"] == "MOOV-12345"


@pytest.mark.asyncio
async def test_card_webhook_success(client: AsyncClient):
    _, client_tok, res_id, tx_ref = await _setup_payment(
        client, "+22672020005", "+22672020006", method="card", hour=12
    )

    payload, sig = _card_webhook(tx_ref, "success")
    resp = await client.post(
        "/api/v1/payments/webhook/card",
        content=json.dumps(payload, separators=(",", ":")),
        headers={"Content-Type": "application/json", "X-Card-Signature": sig},
    )
    assert resp.status_code == 200
    payment_list = await client.get(
        f"/api/v1/payments/reservation/{res_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert payment_list.json()[0]["status"] == "success"


@pytest.mark.asyncio
async def test_webhook_failed_keeps_reservation_pending(client: AsyncClient):
    _, client_tok, res_id, tx_ref = await _setup_payment(
        client, "+22672020007", "+22672020008", method="orange_money", hour=13
    )

    payload, sig = _om_webhook(tx_ref, "FAILED")
    await client.post(
        "/api/v1/payments/webhook/orange_money",
        content=json.dumps(payload, separators=(",", ":")),
        headers={"Content-Type": "application/json", "X-Orange-Signature": sig},
    )

    res_detail = await client.get(
        f"/api/v1/reservations/mine/{res_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert res_detail.json()["status"] == "pending"

    payment_list = await client.get(
        f"/api/v1/payments/reservation/{res_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert payment_list.json()[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_webhook_invalid_signature_rejected(client: AsyncClient):
    _, _, _, tx_ref = await _setup_payment(
        client, "+22672020009", "+22672020010", method="orange_money", hour=14
    )

    payload, _ = _om_webhook(tx_ref, "SUCCESS")
    resp = await client.post(
        "/api/v1/payments/webhook/orange_money",
        content=json.dumps(payload, separators=(",", ":")),
        headers={"Content-Type": "application/json", "X-Orange-Signature": "bad-signature"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_unknown_reference_silently_ignored(client: AsyncClient):
    """Un webhook avec une référence inconnue retourne 200 sans erreur."""
    payload, sig = _om_webhook("GF-OM-UNKNOWN00000", "SUCCESS")
    resp = await client.post(
        "/api/v1/payments/webhook/orange_money",
        content=json.dumps(payload, separators=(",", ":")),
        headers={"Content-Type": "application/json", "X-Orange-Signature": sig},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_unknown_provider_rejected(client: AsyncClient):
    resp = await client.post(
        "/api/v1/payments/webhook/unknown_provider",
        content=b'{"test": 1}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


# ── Reçu ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_receipt_after_success(client: AsyncClient):
    owner_tok, client_tok, res_id, tx_ref = await _setup_payment(
        client, "+22672030001", "+22672030002", method="orange_money", hour=10
    )

    # Obtenir le payment_id
    payments = await client.get(
        f"/api/v1/payments/reservation/{res_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    payment_id = payments.json()[0]["id"]

    # Webhook → SUCCESS
    payload, sig = _om_webhook(tx_ref, "SUCCESS")
    await client.post(
        "/api/v1/payments/webhook/orange_money",
        content=json.dumps(payload, separators=(",", ":")),
        headers={"Content-Type": "application/json", "X-Orange-Signature": sig},
    )

    # Reçu
    receipt = await client.get(
        f"/api/v1/payments/{payment_id}/receipt",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert receipt.status_code == 200
    data = receipt.json()
    assert data["receipt_number"].startswith("REC-")
    assert data["status"] == "success"
    assert data["terrain_name"] == "Terrain Gamma"
    assert data["terrain_city"] == "Bobo-Dioulasso"
    assert data["amount"] == 15.0
    assert data["currency"] == "XOF"
    assert data["duration_minutes"] == 60
    assert data["paid_at"] is not None
    assert data["issued_at"] is not None


@pytest.mark.asyncio
async def test_receipt_not_available_for_pending_payment(client: AsyncClient):
    owner_tok = await _tok(client, {**OWNER, "phone": "+22672030003"})
    client_tok = await _tok(client, {**CLIENT_A, "phone": "+22672030004"})
    terrain_data = await _terrain(client, owner_tok)
    slot_data = await _slot(client, owner_tok, terrain_data["id"], hour=11)
    res = await _reservation(client, client_tok, slot_data["id"])

    init_resp = await client.post(
        "/api/v1/payments/initiate",
        json={"reservation_id": res["id"], "payment_method": "orange_money"},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    payment_id = init_resp.json()["payment_id"]

    receipt = await client.get(
        f"/api/v1/payments/{payment_id}/receipt",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert receipt.status_code == 400


@pytest.mark.asyncio
async def test_receipt_accessible_to_terrain_owner(client: AsyncClient):
    owner_tok, client_tok, res_id, tx_ref = await _setup_payment(
        client, "+22672030005", "+22672030006", method="orange_money", hour=12
    )
    payments = await client.get(
        f"/api/v1/payments/reservation/{res_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    payment_id = payments.json()[0]["id"]

    payload, sig = _om_webhook(tx_ref, "SUCCESS")
    await client.post(
        "/api/v1/payments/webhook/orange_money",
        content=json.dumps(payload, separators=(",", ":")),
        headers={"Content-Type": "application/json", "X-Orange-Signature": sig},
    )

    receipt = await client.get(
        f"/api/v1/payments/{payment_id}/receipt",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert receipt.status_code == 200


# ── Remboursement ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_can_refund_successful_payment(client: AsyncClient):
    owner_tok, client_tok, res_id, tx_ref = await _setup_payment(
        client, "+22672040001", "+22672040002", method="orange_money", hour=10
    )
    payments = await client.get(
        f"/api/v1/payments/reservation/{res_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    payment_id = payments.json()[0]["id"]

    # Webhook → SUCCESS
    payload, sig = _om_webhook(tx_ref, "SUCCESS")
    await client.post(
        "/api/v1/payments/webhook/orange_money",
        content=json.dumps(payload, separators=(",", ":")),
        headers={"Content-Type": "application/json", "X-Orange-Signature": sig},
    )

    # Remboursement
    refund = await client.post(
        f"/api/v1/payments/{payment_id}/refund",
        json={"reason": "Annulation exceptionnelle"},
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert refund.status_code == 200
    assert refund.json()["status"] == "refunded"

    # Réservation → CANCELLED
    res_detail = await client.get(
        f"/api/v1/reservations/mine/{res_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert res_detail.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_client_cannot_refund(client: AsyncClient):
    _, client_tok, res_id, tx_ref = await _setup_payment(
        client, "+22672040003", "+22672040004", method="orange_money", hour=11
    )
    payments = await client.get(
        f"/api/v1/payments/reservation/{res_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    payment_id = payments.json()[0]["id"]

    payload, sig = _om_webhook(tx_ref, "SUCCESS")
    await client.post(
        "/api/v1/payments/webhook/orange_money",
        content=json.dumps(payload, separators=(",", ":")),
        headers={"Content-Type": "application/json", "X-Orange-Signature": sig},
    )

    refund = await client.post(
        f"/api/v1/payments/{payment_id}/refund",
        json={"reason": "essai"},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert refund.status_code == 403


@pytest.mark.asyncio
async def test_cannot_refund_pending_payment(client: AsyncClient):
    owner_tok = await _tok(client, {**OWNER, "phone": "+22672040005"})
    client_tok = await _tok(client, {**CLIENT_A, "phone": "+22672040006"})
    terrain_data = await _terrain(client, owner_tok)
    slot_data = await _slot(client, owner_tok, terrain_data["id"], hour=12)
    res = await _reservation(client, client_tok, slot_data["id"])

    init_resp = await client.post(
        "/api/v1/payments/initiate",
        json={"reservation_id": res["id"], "payment_method": "orange_money"},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    payment_id = init_resp.json()["payment_id"]

    refund = await client.post(
        f"/api/v1/payments/{payment_id}/refund",
        json={"reason": "test"},
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert refund.status_code == 400


# ── Double paiement après SUCCESS ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cannot_pay_already_paid_reservation(client: AsyncClient):
    owner_tok, client_tok, res_id, tx_ref = await _setup_payment(
        client, "+22672050001", "+22672050002", method="orange_money", hour=10
    )

    payload, sig = _om_webhook(tx_ref, "SUCCESS")
    await client.post(
        "/api/v1/payments/webhook/orange_money",
        content=json.dumps(payload, separators=(",", ":")),
        headers={"Content-Type": "application/json", "X-Orange-Signature": sig},
    )

    r2 = await client.post(
        "/api/v1/payments/initiate",
        json={"reservation_id": res_id, "payment_method": "moov_money"},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert r2.status_code == 400
    assert "déjà payée" in r2.json()["detail"].lower()
