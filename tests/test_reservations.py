"""
Tests du module Réservations GestFive.

Couvre :
- Création slot-based et directe
- Doubles réservations → 409
- Historique joueur (paginé, filtre statut)
- Détail avec access control
- Annulation (joueur, admin, mauvais utilisateur)
- Vue propriétaire : par terrain, toutes ses réservations
- Confirmation (CONFIRMED) et clôture (COMPLETED) par le propriétaire
- duration_minutes dans la réponse
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

# ── Fixtures partagées ─────────────────────────────────────────────────────────

OWNER = {
    "firstname": "Ibrahima",
    "lastname": "Traoré",
    "phone": "+22670100001",
    "password": "owner1234",
    "role": "owner",
}

CLIENT_A = {
    "firstname": "Fatou",
    "lastname": "Sawadogo",
    "phone": "+22670100002",
    "password": "client1234",
    "role": "client",
}

CLIENT_B = {
    "firstname": "Moussa",
    "lastname": "Koné",
    "phone": "+22670100003",
    "password": "client1234",
    "role": "client",
}

TERRAIN_BODY = {
    "name": "Terrain Beta",
    "address": "Zone B, Ouaga",
    "city": "Ouagadougou",
    "price_per_hour": 12.0,
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


async def _token(client: AsyncClient, payload: dict) -> str:
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.json()
    return resp.json()["access_token"]


async def _terrain(client: AsyncClient, token: str, body: dict = TERRAIN_BODY) -> dict:
    resp = await client.post(
        "/api/v1/terrains/",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()


def _next_monday_slot(hour: int = 10, duration_h: int = 1) -> dict:
    """Créneau futur un lundi (toujours dans les horaires 08-22)."""
    now = datetime.now(timezone.utc)
    days = (7 - now.weekday()) % 7 or 7
    monday = (now + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return {
        "start_datetime": monday.isoformat(),
        "end_datetime": (monday + timedelta(hours=duration_h)).isoformat(),
    }


async def _create_slot(client: AsyncClient, token: str, terrain_id: str, hour: int = 10) -> dict:
    resp = await client.post(
        f"/api/v1/terrains/{terrain_id}/slots",
        json=_next_monday_slot(hour=hour),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()


# ── Création slot-based ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_slot_based_reservation(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671100001"})
    client_tok = await _token(client, {**CLIENT_A, "phone": "+22671100002"})
    terrain = await _terrain(client, owner_tok)

    slot = await _create_slot(client, owner_tok, terrain["id"], hour=10)

    resp = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["time_slot_id"] == slot["id"]
    assert data["total_price"] == pytest.approx(12.0)
    assert data["duration_minutes"] == 60
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_slot_based_price_2h(client: AsyncClient):
    """2 heures → total_price = price_per_hour × 2."""
    owner_tok = await _token(client, {**OWNER, "phone": "+22671100003"})
    client_tok = await _token(client, {**CLIENT_A, "phone": "+22671100004"})
    terrain = await _terrain(client, owner_tok)

    s = _next_monday_slot(hour=14, duration_h=2)
    slot_2h = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots",
        json=s,
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert slot_2h.status_code == 201
    slot_id = slot_2h.json()["id"]

    resp = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot_id},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 201
    assert resp.json()["total_price"] == pytest.approx(24.0)
    assert resp.json()["duration_minutes"] == 120


# ── Création directe ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_direct_reservation(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671200001"})
    client_tok = await _token(client, {**CLIENT_A, "phone": "+22671200002"})
    terrain = await _terrain(client, owner_tok)

    s = _next_monday_slot(hour=16)
    resp = await client.post(
        "/api/v1/reservations/",
        json={
            "terrain_id": terrain["id"],
            "start_datetime": s["start_datetime"],
            "end_datetime": s["end_datetime"],
        },
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["terrain_id"] == terrain["id"]
    assert data["time_slot_id"] is None
    assert data["total_price"] == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_direct_reservation_past_time_rejected(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671200003"})
    client_tok = await _token(client, {**CLIENT_A, "phone": "+22671200004"})
    terrain = await _terrain(client, owner_tok)

    past = datetime.now(timezone.utc) - timedelta(hours=2)
    resp = await client.post(
        "/api/v1/reservations/",
        json={
            "terrain_id": terrain["id"],
            "start_datetime": past.isoformat(),
            "end_datetime": (past + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_missing_fields_rejected_422(client: AsyncClient):
    """terrain_id seul sans start/end → 422."""
    owner_tok = await _token(client, {**OWNER, "phone": "+22671200005"})
    client_tok = await _token(client, {**CLIENT_A, "phone": "+22671200006"})
    terrain = await _terrain(client, owner_tok)

    resp = await client.post(
        "/api/v1/reservations/",
        json={"terrain_id": terrain["id"]},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 422


# ── Doubles réservations ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_double_slot_booking_rejected(client: AsyncClient):
    """Deux clients tentent de réserver le même créneau."""
    owner_tok = await _token(client, {**OWNER, "phone": "+22671300001"})
    tok_a = await _token(client, {**CLIENT_A, "phone": "+22671300002"})
    tok_b = await _token(client, {**CLIENT_B, "phone": "+22671300003"})
    terrain = await _terrain(client, owner_tok)
    slot = await _create_slot(client, owner_tok, terrain["id"], hour=10)

    r1 = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_direct_double_booking_rejected(client: AsyncClient):
    """Deux réservations directes qui se chevauchent → 400."""
    owner_tok = await _token(client, {**OWNER, "phone": "+22671300004"})
    tok_a = await _token(client, {**CLIENT_A, "phone": "+22671300005"})
    tok_b = await _token(client, {**CLIENT_B, "phone": "+22671300006"})
    terrain = await _terrain(client, owner_tok)

    s = _next_monday_slot(hour=15, duration_h=2)
    body = {
        "terrain_id": terrain["id"],
        "start_datetime": s["start_datetime"],
        "end_datetime": s["end_datetime"],
    }
    r1 = await client.post(
        "/api/v1/reservations/", json=body,
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/api/v1/reservations/", json=body,
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert r2.status_code == 400


# ── Historique joueur ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_mine_returns_own_reservations(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671400001"})
    tok = await _token(client, {**CLIENT_A, "phone": "+22671400002"})
    terrain = await _terrain(client, owner_tok)

    # 2 réservations
    s1 = await _create_slot(client, owner_tok, terrain["id"], hour=10)
    s2 = await _create_slot(client, owner_tok, terrain["id"], hour=11)
    for sid in [s1["id"], s2["id"]]:
        r = await client.post(
            "/api/v1/reservations/",
            json={"time_slot_id": sid},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 201

    resp = await client.get(
        "/api/v1/reservations/mine",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert all("duration_minutes" in r for r in data["items"])


@pytest.mark.asyncio
async def test_list_mine_status_filter(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671400003"})
    tok = await _token(client, {**CLIENT_A, "phone": "+22671400004"})
    terrain = await _terrain(client, owner_tok)

    slot = await _create_slot(client, owner_tok, terrain["id"], hour=12)
    res = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {tok}"},
    )
    res_id = res.json()["id"]

    # Annuler la réservation
    await client.patch(
        f"/api/v1/reservations/{res_id}/cancel",
        headers={"Authorization": f"Bearer {tok}"},
    )

    pending = await client.get(
        "/api/v1/reservations/mine",
        params={"status": "pending"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert pending.json()["total"] == 0

    cancelled = await client.get(
        "/api/v1/reservations/mine",
        params={"status": "cancelled"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert cancelled.json()["total"] == 1


# ── Détail avec access control ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_detail_accessible_to_player(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671500001"})
    tok = await _token(client, {**CLIENT_A, "phone": "+22671500002"})
    terrain = await _terrain(client, owner_tok)
    slot = await _create_slot(client, owner_tok, terrain["id"], hour=10)

    res = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {tok}"},
    )
    res_id = res.json()["id"]

    detail = await client.get(
        f"/api/v1/reservations/mine/{res_id}",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == res_id


@pytest.mark.asyncio
async def test_detail_accessible_to_terrain_owner(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671500003"})
    client_tok = await _token(client, {**CLIENT_A, "phone": "+22671500004"})
    terrain = await _terrain(client, owner_tok)
    slot = await _create_slot(client, owner_tok, terrain["id"], hour=11)

    res = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    res_id = res.json()["id"]

    # Le propriétaire du terrain peut voir le détail
    detail = await client.get(
        f"/api/v1/reservations/mine/{res_id}",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert detail.status_code == 200


@pytest.mark.asyncio
async def test_detail_forbidden_for_other_client(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671500005"})
    tok_a = await _token(client, {**CLIENT_A, "phone": "+22671500006"})
    tok_b = await _token(client, {**CLIENT_B, "phone": "+22671500007"})
    terrain = await _terrain(client, owner_tok)
    slot = await _create_slot(client, owner_tok, terrain["id"], hour=12)

    res = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    res_id = res.json()["id"]

    other = await client.get(
        f"/api/v1/reservations/mine/{res_id}",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert other.status_code == 403


# ── Annulation ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_own_reservation(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671600001"})
    tok = await _token(client, {**CLIENT_A, "phone": "+22671600002"})
    terrain = await _terrain(client, owner_tok)
    slot = await _create_slot(client, owner_tok, terrain["id"], hour=10)

    res = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {tok}"},
    )
    res_id = res.json()["id"]

    cancel = await client.patch(
        f"/api/v1/reservations/{res_id}/cancel",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_releases_slot(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671600003"})
    tok = await _token(client, {**CLIENT_A, "phone": "+22671600004"})
    terrain = await _terrain(client, owner_tok)
    slot = await _create_slot(client, owner_tok, terrain["id"], hour=11)
    slot_start = slot["start_datetime"]
    slot_end = slot["end_datetime"]

    res = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {tok}"},
    )
    res_id = res.json()["id"]

    await client.patch(
        f"/api/v1/reservations/{res_id}/cancel",
        headers={"Authorization": f"Bearer {tok}"},
    )

    avail = await client.get(
        f"/api/v1/terrains/{terrain['id']}/availability",
        params={"start_datetime": slot_start, "end_datetime": slot_end},
    )
    assert avail.json()["available"] is True


@pytest.mark.asyncio
async def test_cancel_forbidden_for_other_user(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671600005"})
    tok_a = await _token(client, {**CLIENT_A, "phone": "+22671600006"})
    tok_b = await _token(client, {**CLIENT_B, "phone": "+22671600007"})
    terrain = await _terrain(client, owner_tok)
    slot = await _create_slot(client, owner_tok, terrain["id"], hour=12)

    res = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    res_id = res.json()["id"]

    other_cancel = await client.patch(
        f"/api/v1/reservations/{res_id}/cancel",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert other_cancel.status_code == 403


@pytest.mark.asyncio
async def test_cancel_already_cancelled_rejected(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671600008"})
    tok = await _token(client, {**CLIENT_A, "phone": "+22671600009"})
    terrain = await _terrain(client, owner_tok)
    slot = await _create_slot(client, owner_tok, terrain["id"], hour=13)

    res = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {tok}"},
    )
    res_id = res.json()["id"]

    await client.patch(
        f"/api/v1/reservations/{res_id}/cancel",
        headers={"Authorization": f"Bearer {tok}"},
    )
    second = await client.patch(
        f"/api/v1/reservations/{res_id}/cancel",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert second.status_code == 400


# ── Vue propriétaire ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_list_terrain_reservations(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671700001"})
    tok_a = await _token(client, {**CLIENT_A, "phone": "+22671700002"})
    tok_b = await _token(client, {**CLIENT_B, "phone": "+22671700003"})
    terrain = await _terrain(client, owner_tok)

    s1 = await _create_slot(client, owner_tok, terrain["id"], hour=10)
    s2 = await _create_slot(client, owner_tok, terrain["id"], hour=11)
    for tok, sid in [(tok_a, s1["id"]), (tok_b, s2["id"])]:
        r = await client.post(
            "/api/v1/reservations/",
            json={"time_slot_id": sid},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 201

    resp = await client.get(
        f"/api/v1/reservations/terrain/{terrain['id']}",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_owner_list_all_reservations(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671700004"})
    tok = await _token(client, {**CLIENT_A, "phone": "+22671700005"})
    terrain = await _terrain(client, owner_tok)

    slot = await _create_slot(client, owner_tok, terrain["id"], hour=14)
    await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {tok}"},
    )

    resp = await client.get(
        "/api/v1/reservations/owner/all",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


@pytest.mark.asyncio
async def test_client_cannot_access_owner_routes(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671700006"})
    client_tok = await _token(client, {**CLIENT_A, "phone": "+22671700007"})
    terrain = await _terrain(client, owner_tok)

    resp = await client.get(
        f"/api/v1/reservations/terrain/{terrain['id']}",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_cannot_see_other_owner_terrain(client: AsyncClient):
    """Un propriétaire ne voit pas les réservations d'un terrain qui ne lui appartient pas."""
    owner1_tok = await _token(client, {**OWNER, "phone": "+22671700008"})
    owner2_tok = await _token(
        client,
        {"firstname": "X", "lastname": "Y", "phone": "+22671700009",
         "password": "owner1234", "role": "owner"},
    )
    terrain = await _terrain(client, owner1_tok)

    resp = await client.get(
        f"/api/v1/reservations/terrain/{terrain['id']}",
        headers={"Authorization": f"Bearer {owner2_tok}"},
    )
    assert resp.status_code == 403


# ── Gestion des statuts par le propriétaire ───────────────────────────────────

@pytest.mark.asyncio
async def test_owner_confirms_reservation(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671800001"})
    client_tok = await _token(client, {**CLIENT_A, "phone": "+22671800002"})
    terrain = await _terrain(client, owner_tok)
    slot = await _create_slot(client, owner_tok, terrain["id"], hour=10)

    res = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    res_id = res.json()["id"]
    assert res.json()["status"] == "pending"

    confirm = await client.patch(
        f"/api/v1/reservations/{res_id}/status",
        json={"status": "confirmed"},
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "confirmed"


@pytest.mark.asyncio
async def test_owner_marks_reservation_completed(client: AsyncClient):
    owner_tok = await _token(client, {**OWNER, "phone": "+22671800003"})
    client_tok = await _token(client, {**CLIENT_A, "phone": "+22671800004"})
    terrain = await _terrain(client, owner_tok)
    slot = await _create_slot(client, owner_tok, terrain["id"], hour=11)

    res = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    res_id = res.json()["id"]

    done = await client.patch(
        f"/api/v1/reservations/{res_id}/status",
        json={"status": "completed"},
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert done.status_code == 200
    assert done.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_other_owner_cannot_update_status(client: AsyncClient):
    owner1_tok = await _token(client, {**OWNER, "phone": "+22671800005"})
    owner2_tok = await _token(
        client,
        {"firstname": "A", "lastname": "B", "phone": "+22671800006",
         "password": "owner1234", "role": "owner"},
    )
    client_tok = await _token(client, {**CLIENT_A, "phone": "+22671800007"})
    terrain = await _terrain(client, owner1_tok)
    slot = await _create_slot(client, owner1_tok, terrain["id"], hour=12)

    res = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot["id"]},
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    res_id = res.json()["id"]

    resp = await client.patch(
        f"/api/v1/reservations/{res_id}/status",
        json={"status": "confirmed"},
        headers={"Authorization": f"Bearer {owner2_tok}"},
    )
    assert resp.status_code == 403
