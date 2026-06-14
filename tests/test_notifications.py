"""
Tests du système de notifications GestFive.

Couvre :
- Liste vide pour un nouvel utilisateur
- Création automatique lors d'un paiement SUCCESS (webhook)
- Création automatique lors d'une annulation
- Marquage lu/non-lu (unitaire et en lot)
- Compteur de non-lus
- Filtre unread_only
- Suppression
- Enregistrement du token FCM
- Contrôle d'accès (ne peut pas lire les notifications d'un autre utilisateur)
- Rappels de match (endpoint admin, idempotence)
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

# ── Données de base ────────────────────────────────────────────────────────────

_OWNER = {
    "firstname": "Serge",
    "lastname": "Nikiéma",
    "phone": "+22670010001",
    "password": "owner1234",
    "role": "owner",
}
_CLIENT = {
    "firstname": "Mariam",
    "lastname": "Ouédraogo",
    "phone": "+22670010002",
    "password": "client1234",
    "role": "client",
}
_ADMIN = {
    "firstname": "Admin",
    "lastname": "GestFive",
    "phone": "+22670010003",
    "password": "admin1234",
    "role": "admin",
}
_TERRAIN_BODY = {
    "name": "Terrain Notif Test",
    "address": "Zone E, Ouaga",
    "city": "Ouagadougou",
    "price_per_hour": 10.0,
    "opening_hours": {
        "monday": {"open": "08:00", "close": "22:00", "is_closed": False},
        "tuesday": {"open": "08:00", "close": "22:00", "is_closed": False},
        "wednesday": {"open": "08:00", "close": "22:00", "is_closed": False},
        "thursday": {"open": "08:00", "close": "22:00", "is_closed": False},
        "friday": {"open": "08:00", "close": "22:00", "is_closed": False},
        "saturday": {"open": "09:00", "close": "20:00", "is_closed": False},
        "sunday": {"open": "00:00", "close": "00:00", "is_closed": True},
    },
}
_OM_SECRET = "dev-om-webhook-secret"


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _reg(client: AsyncClient, payload: dict) -> str:
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.json()
    return r.json()["access_token"]


async def _terrain(client: AsyncClient, tok: str) -> dict:
    r = await client.post(
        "/api/v1/terrains/",
        json=_TERRAIN_BODY,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 201, r.json()
    return r.json()


def _next_monday(hour: int = 10) -> dict:
    now = datetime.now(timezone.utc)
    days = (7 - now.weekday()) % 7 or 7
    start = (now + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return {
        "start_datetime": start.isoformat(),
        "end_datetime": (start + timedelta(hours=1)).isoformat(),
    }


async def _slot(client: AsyncClient, tok: str, terrain_id: str, hour: int = 10) -> dict:
    r = await client.post(
        f"/api/v1/terrains/{terrain_id}/slots",
        json=_next_monday(hour=hour),
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 201, r.json()
    return r.json()


async def _book(client: AsyncClient, tok: str, slot_id: str) -> dict:
    r = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot_id},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 201, r.json()
    return r.json()


async def _initiate_payment(client: AsyncClient, tok: str, reservation_id: str) -> dict:
    r = await client.post(
        "/api/v1/payments/initiate",
        json={"reservation_id": reservation_id, "payment_method": "orange_money"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 201, r.json()
    return r.json()


def _sign(secret: str, payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _webhook_success(client: AsyncClient, transaction_ref: str) -> None:
    payload = {
        "txnid": transaction_ref,
        "status": "SUCCESS",
        "notifToken": "prov-abc123",
    }
    sig = _sign(_OM_SECRET, payload)
    r = await client.post(
        "/api/v1/payments/webhook/orange_money",
        json=payload,
        headers={"X-Orange-Signature": sig},
    )
    assert r.status_code == 200, r.json()


async def _cancel(client: AsyncClient, tok: str, res_id: str) -> None:
    r = await client.patch(
        f"/api/v1/reservations/{res_id}/cancel",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.json()


async def _notifications(
    client: AsyncClient, tok: str, unread_only: bool = False
) -> list[dict]:
    params = "?unread_only=true" if unread_only else ""
    r = await client.get(
        f"/api/v1/notifications/{params}",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.json()
    return r.json()["items"]


# ── Contrôle d'accès ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_requires_auth(client: AsyncClient):
    for path in ["/", "/unread-count"]:
        r = await client.get(f"/api/v1/notifications{path}")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_reminders_requires_admin(client: AsyncClient):
    """Un client ou owner ne peut pas déclencher les rappels → 403."""
    tok = await _reg(client, {**_CLIENT, "phone": "+22671010001"})
    r = await client.post(
        "/api/v1/notifications/send-reminders",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


# ── Liste vide ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_list(client: AsyncClient):
    tok = await _reg(client, {**_CLIENT, "phone": "+22672010001"})
    notifs = await _notifications(client, tok)
    assert notifs == []

    r = await client.get(
        "/api/v1/notifications/unread-count",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.json()["count"] == 0


# ── Création automatique ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notification_on_payment_success(client: AsyncClient):
    """Webhook SUCCESS → 2 notifications : PAYMENT_SUCCESS + RESERVATION_CONFIRMED."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22673010001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22673010002"})
    t = await _terrain(client, owner_tok)
    s = await _slot(client, owner_tok, t["id"])
    res = await _book(client, client_tok, s["id"])
    payment = await _initiate_payment(client, client_tok, res["id"])

    await _webhook_success(client, payment["transaction_reference"])

    notifs = await _notifications(client, client_tok)
    types = {n["type"] for n in notifs}
    assert "payment_success" in types
    assert "reservation_confirmed" in types
    # Toutes non-lues au départ
    assert all(not n["is_read"] for n in notifs)


@pytest.mark.asyncio
async def test_notification_on_cancellation(client: AsyncClient):
    """Annulation d'une réservation → notification CANCELLATION pour le joueur."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22674010001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22674010002"})
    t = await _terrain(client, owner_tok)
    s = await _slot(client, owner_tok, t["id"])
    res = await _book(client, client_tok, s["id"])

    await _cancel(client, client_tok, res["id"])

    notifs = await _notifications(client, client_tok)
    types = {n["type"] for n in notifs}
    assert "cancellation" in types
    # Lien vers la réservation
    cancellation = next(n for n in notifs if n["type"] == "cancellation")
    assert cancellation["reservation_id"] == res["id"]


# ── Marquage lu ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_single_as_read(client: AsyncClient):
    """PATCH /{id}/read → is_read=True, read_at renseigné."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22675010001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22675010002"})
    t = await _terrain(client, owner_tok)
    s = await _slot(client, owner_tok, t["id"])
    res = await _book(client, client_tok, s["id"])
    await _cancel(client, client_tok, res["id"])

    notifs = await _notifications(client, client_tok)
    notif_id = notifs[0]["id"]

    r = await client.patch(
        f"/api/v1/notifications/{notif_id}/read",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["is_read"] is True
    assert data["read_at"] is not None


@pytest.mark.asyncio
async def test_unread_count_decreases_on_read(client: AsyncClient):
    """Après lecture, le compteur de non-lus diminue."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22676010001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22676010002"})
    t = await _terrain(client, owner_tok)
    s = await _slot(client, owner_tok, t["id"])
    res = await _book(client, client_tok, s["id"])
    await _cancel(client, client_tok, res["id"])

    # 1 non-lue
    r = await client.get(
        "/api/v1/notifications/unread-count",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert r.json()["count"] == 1

    # Marquer comme lue
    notifs = await _notifications(client, client_tok)
    await client.patch(
        f"/api/v1/notifications/{notifs[0]['id']}/read",
        headers={"Authorization": f"Bearer {client_tok}"},
    )

    # Maintenant 0
    r2 = await client.get(
        "/api/v1/notifications/unread-count",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert r2.json()["count"] == 0


@pytest.mark.asyncio
async def test_mark_all_read(client: AsyncClient):
    """PATCH /read-all → toutes les notifications marquées lues."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22677010001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22677010002"})
    t = await _terrain(client, owner_tok)

    # Créer 2 notifications via 2 annulations
    s1 = await _slot(client, owner_tok, t["id"], hour=10)
    s2 = await _slot(client, owner_tok, t["id"], hour=12)
    r1 = await _book(client, client_tok, s1["id"])
    r2 = await _book(client, client_tok, s2["id"])
    await _cancel(client, client_tok, r1["id"])
    await _cancel(client, client_tok, r2["id"])

    # Vérifier 2 non-lues
    cnt_r = await client.get(
        "/api/v1/notifications/unread-count",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert cnt_r.json()["count"] == 2

    # Tout marquer lu
    bulk_r = await client.patch(
        "/api/v1/notifications/read-all",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert bulk_r.status_code == 200
    assert bulk_r.json()["updated"] == 2

    # Compteur = 0
    cnt_r2 = await client.get(
        "/api/v1/notifications/unread-count",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert cnt_r2.json()["count"] == 0


@pytest.mark.asyncio
async def test_filter_unread_only(client: AsyncClient):
    """?unread_only=true retourne seulement les non-lues."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22678010001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22678010002"})
    t = await _terrain(client, owner_tok)

    s1 = await _slot(client, owner_tok, t["id"], hour=10)
    s2 = await _slot(client, owner_tok, t["id"], hour=12)
    r1 = await _book(client, client_tok, s1["id"])
    r2 = await _book(client, client_tok, s2["id"])
    await _cancel(client, client_tok, r1["id"])
    await _cancel(client, client_tok, r2["id"])

    # Marquer la première comme lue
    notifs = await _notifications(client, client_tok)
    await client.patch(
        f"/api/v1/notifications/{notifs[0]['id']}/read",
        headers={"Authorization": f"Bearer {client_tok}"},
    )

    # Filtre unread_only → 1 seule
    unread = await _notifications(client, client_tok, unread_only=True)
    assert len(unread) == 1
    assert unread[0]["is_read"] is False


# ── Suppression ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_notification(client: AsyncClient):
    """DELETE /{id} → 204, la notification disparaît de la liste."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22679010001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22679010002"})
    t = await _terrain(client, owner_tok)
    s = await _slot(client, owner_tok, t["id"])
    res = await _book(client, client_tok, s["id"])
    await _cancel(client, client_tok, res["id"])

    notifs = await _notifications(client, client_tok)
    notif_id = notifs[0]["id"]

    del_r = await client.delete(
        f"/api/v1/notifications/{notif_id}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert del_r.status_code == 204

    remaining = await _notifications(client, client_tok)
    assert all(n["id"] != notif_id for n in remaining)


# ── Isolation utilisateur ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cannot_read_other_user_notification(client: AsyncClient):
    """Un utilisateur ne peut pas marquer la notification d'un autre comme lue."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22680010001"})
    client_a_tok = await _reg(client, {**_CLIENT, "phone": "+22680010002"})
    client_b_tok = await _reg(
        client, {"firstname": "X", "lastname": "Y", "phone": "+22680010003",
                 "password": "pass1234", "role": "client"}
    )

    t = await _terrain(client, owner_tok)
    s = await _slot(client, owner_tok, t["id"])
    res = await _book(client, client_a_tok, s["id"])
    await _cancel(client, client_a_tok, res["id"])

    notifs = await _notifications(client, client_a_tok)
    notif_id = notifs[0]["id"]

    # client_b essaie de marquer la notif de client_a → 403
    r = await client.patch(
        f"/api/v1/notifications/{notif_id}/read",
        headers={"Authorization": f"Bearer {client_b_tok}"},
    )
    assert r.status_code == 403


# ── Token FCM ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_fcm_token(client: AsyncClient):
    """POST /fcm-token → 204, le token est bien enregistré."""
    tok = await _reg(client, {**_CLIENT, "phone": "+22681010001"})

    r = await client.post(
        "/api/v1/notifications/fcm-token",
        json={"token": "fcm_test_token_abc123xyz"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_register_fcm_token_empty_rejected(client: AsyncClient):
    """Un token vide est rejeté par la validation Pydantic → 422."""
    tok = await _reg(client, {**_CLIENT, "phone": "+22682010001"})

    r = await client.post(
        "/api/v1/notifications/fcm-token",
        json={"token": ""},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 422


# ── Rappels (admin) ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_reminders_admin(client: AsyncClient):
    """Admin peut appeler /send-reminders — retourne ReminderResult."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22683010001"})

    r = await client.post(
        "/api/v1/notifications/send-reminders",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "sent" in data
    assert "message" in data
    # Aucune réservation dans la fenêtre [+30min, +90min] → sent=0
    assert data["sent"] == 0


@pytest.mark.asyncio
async def test_reminders_idempotent(client: AsyncClient):
    """
    Appeler /send-reminders deux fois ne duplique pas les notifications.
    (Testé sur la logique reminder_already_sent — ici sent=0 les deux fois
    car la fenêtre de test est vide. Le test unitaire de l'idempotence
    est couvert par le repository test reminder_already_sent.)
    """
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22684010001"})

    r1 = await client.post(
        "/api/v1/notifications/send-reminders",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    r2 = await client.post(
        "/api/v1/notifications/send-reminders",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r1.json()["sent"] == r2.json()["sent"] == 0


# ── Pagination ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pagination(client: AsyncClient):
    """skip/limit fonctionnent sur la liste des notifications."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22685010001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22685010002"})
    t = await _terrain(client, owner_tok)

    # Créer 3 notifications via 3 annulations
    for hour in [10, 12, 14]:
        s = await _slot(client, owner_tok, t["id"], hour=hour)
        r = await _book(client, client_tok, s["id"])
        await _cancel(client, client_tok, r["id"])

    p1 = await client.get(
        "/api/v1/notifications/?skip=0&limit=2",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    d1 = p1.json()
    assert d1["total"] == 3
    assert len(d1["items"]) == 2
    assert d1["has_more"] is True

    p2 = await client.get(
        "/api/v1/notifications/?skip=2&limit=2",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    d2 = p2.json()
    assert len(d2["items"]) == 1
    assert d2["has_more"] is False
