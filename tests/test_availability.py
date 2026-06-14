"""
Tests du moteur de disponibilité GestFive.

Couvre :
- Vérification de disponibilité (horaires, conflits)
- Création de créneaux
- Génération en masse
- Réservation par créneau (slot-based booking)
- Libération du créneau lors d'une annulation
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

# ── Fixtures helpers ───────────────────────────────────────────────────────────

OWNER_PAYLOAD = {
    "firstname": "Omar",
    "lastname": "Diallo",
    "phone": "+22671000001",
    "password": "owner123",
    "role": "owner",
}

CLIENT_PAYLOAD = {
    "firstname": "Aicha",
    "lastname": "Koné",
    "phone": "+22671000002",
    "password": "client123",
    "role": "client",
}

OPENING_HOURS = {
    "monday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "tuesday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "wednesday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "thursday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "friday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "saturday": {"open": "09:00", "close": "20:00", "is_closed": False},
    "sunday": {"open": "00:00", "close": "00:00", "is_closed": True},
}

TERRAIN_PAYLOAD = {
    "name": "Five Star Arena",
    "address": "Rue 15, Sector 30",
    "city": "Ouagadougou",
    "price_per_hour": 10.0,
    "opening_hours": OPENING_HOURS,
}


async def _register_and_token(client: AsyncClient, payload: dict) -> str:
    resp = await client.post("/api/v1/auth/register", json=payload)
    return resp.json()["access_token"]


async def _create_terrain(client: AsyncClient, token: str) -> dict:
    resp = await client.post(
        "/api/v1/terrains/",
        json=TERRAIN_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()


def _future_slot(
    offset_hours: int = 24,
    duration_hours: int = 1,
) -> dict:
    """Crée un créneau futur un jour ouvré (lundi prochain ou +N heures)."""
    # Calcul d'une date future à heure fixe (10h UTC un lundi)
    now = datetime.now(timezone.utc)
    # On cherche le prochain lundi >= demain
    days_ahead = (7 - now.weekday()) % 7 or 7
    monday = now + timedelta(days=days_ahead)
    start = monday.replace(hour=10 + offset_hours % 10, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=duration_hours)
    return {
        "start_datetime": start.isoformat(),
        "end_datetime": end.isoformat(),
    }


# ── Tests : vérification de disponibilité ─────────────────────────────────────

@pytest.mark.asyncio
async def test_availability_no_opening_hours(client: AsyncClient):
    """Sans horaires définis, la disponibilité est toujours vraie."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671001001"})
    resp = await client.post(
        "/api/v1/terrains/",
        json={**TERRAIN_PAYLOAD, "opening_hours": {}},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    terrain_id = resp.json()["id"]

    slot = _future_slot()
    check = await client.get(
        f"/api/v1/terrains/{terrain_id}/availability",
        params={"start_datetime": slot["start_datetime"], "end_datetime": slot["end_datetime"]},
    )
    assert check.status_code == 200
    assert check.json()["available"] is True


@pytest.mark.asyncio
async def test_availability_within_hours(client: AsyncClient):
    """Créneau dans les horaires d'ouverture → disponible."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671001002"})
    terrain = await _create_terrain(client, owner_token)
    terrain_id = terrain["id"]

    slot = _future_slot()
    check = await client.get(
        f"/api/v1/terrains/{terrain_id}/availability",
        params={"start_datetime": slot["start_datetime"], "end_datetime": slot["end_datetime"]},
    )
    assert check.status_code == 200
    assert check.json()["available"] is True


@pytest.mark.asyncio
async def test_availability_conflict_with_existing_slot(client: AsyncClient):
    """Un créneau existant bloque la disponibilité."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671001003"})
    terrain = await _create_terrain(client, owner_token)
    terrain_id = terrain["id"]
    slot = _future_slot(offset_hours=0)

    # Créer un premier créneau
    create_resp = await client.post(
        f"/api/v1/terrains/{terrain_id}/slots",
        json=slot,
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert create_resp.status_code == 201

    # Vérifier qu'il bloque la disponibilité
    check = await client.get(
        f"/api/v1/terrains/{terrain_id}/availability",
        params={"start_datetime": slot["start_datetime"], "end_datetime": slot["end_datetime"]},
    )
    assert check.status_code == 200
    data = check.json()
    assert data["available"] is False
    assert len(data["conflicts"]) == 1


@pytest.mark.asyncio
async def test_availability_outside_opening_hours(client: AsyncClient):
    """Créneau en dehors des horaires → non disponible."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671001004"})
    terrain = await _create_terrain(client, owner_token)
    terrain_id = terrain["id"]

    # 03:00-04:00 : avant l'ouverture (08:00)
    now = datetime.now(timezone.utc)
    days_ahead = (7 - now.weekday()) % 7 or 7
    monday = (now + timedelta(days=days_ahead)).replace(
        hour=3, minute=0, second=0, microsecond=0
    )
    end = monday + timedelta(hours=1)

    check = await client.get(
        f"/api/v1/terrains/{terrain_id}/availability",
        params={
            "start_datetime": monday.isoformat(),
            "end_datetime": end.isoformat(),
        },
    )
    assert check.status_code == 200
    assert check.json()["available"] is False
    assert "ouverture" in check.json()["reason"].lower()


# ── Tests : création de créneaux ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_slot_success(client: AsyncClient):
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671002001"})
    terrain = await _create_terrain(client, owner_token)

    slot = _future_slot()
    resp = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots",
        json=slot,
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "available"
    assert data["duration_minutes"] == 60


@pytest.mark.asyncio
async def test_create_slot_duplicate_conflict(client: AsyncClient):
    """Deux créneaux identiques → conflit."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671002002"})
    terrain = await _create_terrain(client, owner_token)
    slot = _future_slot(offset_hours=1)

    await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots",
        json=slot,
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    resp = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots",
        json=slot,
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_slot_requires_owner(client: AsyncClient):
    """Un CLIENT ne peut pas créer de créneaux."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671002003"})
    client_token = await _register_and_token(client, {**CLIENT_PAYLOAD, "phone": "+22671002004"})
    terrain = await _create_terrain(client, owner_token)

    resp = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots",
        json=_future_slot(offset_hours=2),
        headers={"Authorization": f"Bearer {client_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_slot_past_datetime(client: AsyncClient):
    """Un créneau dans le passé est rejeté par la validation Pydantic."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671002005"})
    terrain = await _create_terrain(client, owner_token)

    past = datetime.now(timezone.utc) - timedelta(hours=2)
    resp = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots",
        json={
            "start_datetime": past.isoformat(),
            "end_datetime": (past + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 422


# ── Tests : génération en masse ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_slots_basic(client: AsyncClient):
    """Génère des créneaux horaires pour une semaine ouverte."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671003001"})
    terrain = await _create_terrain(client, owner_token)

    # Semaine dans 2 semaines pour être sûr d'être dans le futur
    now = datetime.now(timezone.utc)
    days_ahead = (7 - now.weekday()) % 7 or 7
    next_monday = (now + timedelta(days=days_ahead + 7)).date()
    next_sunday = next_monday + timedelta(days=6)

    resp = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots/generate",
        json={
            "date_from": next_monday.isoformat(),
            "date_to": next_sunday.isoformat(),
            "duration_minutes": 60,
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["created_count"] > 0
    # Lundi-samedi = 6 jours ouverts × 14h (8h-22h) = 84 créneaux
    # Dimanche fermé → 6 jours × 14 = 84 créneaux (lundi-vendredi 14h, samedi 11h)
    assert data["skipped_count"] == 0


@pytest.mark.asyncio
async def test_generate_slots_skips_existing(client: AsyncClient):
    """Les créneaux générés ne créent pas de doublons."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671003002"})
    terrain = await _create_terrain(client, owner_token)

    now = datetime.now(timezone.utc)
    days_ahead = (7 - now.weekday()) % 7 or 7
    target_monday = (now + timedelta(days=days_ahead + 7)).date()

    generate_payload = {
        "date_from": target_monday.isoformat(),
        "date_to": target_monday.isoformat(),
        "duration_minutes": 60,
    }

    # Première génération
    resp1 = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots/generate",
        json=generate_payload,
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    created_first = resp1.json()["created_count"]
    assert created_first > 0

    # Deuxième génération → tout est ignoré
    resp2 = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots/generate",
        json=generate_payload,
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp2.json()["created_count"] == 0
    assert resp2.json()["skipped_count"] == created_first


# ── Tests : réservation par créneau ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_book_slot_success(client: AsyncClient):
    """Un client réserve un créneau AVAILABLE → statut passe à BOOKED."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671004001"})
    client_token = await _register_and_token(client, {**CLIENT_PAYLOAD, "phone": "+22671004002"})
    terrain = await _create_terrain(client, owner_token)

    # Propriétaire crée un créneau
    slot_resp = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots",
        json=_future_slot(offset_hours=3),
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert slot_resp.status_code == 201
    slot_id = slot_resp.json()["id"]

    # Client réserve ce créneau
    reservation_resp = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot_id},
        headers={"Authorization": f"Bearer {client_token}"},
    )
    assert reservation_resp.status_code == 201
    res_data = reservation_resp.json()
    assert res_data["time_slot_id"] == slot_id
    assert res_data["total_price"] == 10.0  # 1h × 10€

    # Le créneau est maintenant BOOKED
    check = await client.get(
        f"/api/v1/terrains/{terrain['id']}/availability",
        params={
            "start_datetime": slot_resp.json()["start_datetime"],
            "end_datetime": slot_resp.json()["end_datetime"],
        },
    )
    assert check.json()["available"] is False


@pytest.mark.asyncio
async def test_book_already_booked_slot(client: AsyncClient):
    """Réserver un créneau déjà BOOKED → 400."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671004003"})
    client1_token = await _register_and_token(client, {**CLIENT_PAYLOAD, "phone": "+22671004004"})
    client2_token = await _register_and_token(
        client, {**CLIENT_PAYLOAD, "phone": "+22671004005"}
    )
    terrain = await _create_terrain(client, owner_token)

    slot_resp = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots",
        json=_future_slot(offset_hours=4),
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    slot_id = slot_resp.json()["id"]

    # Client 1 réserve
    r1 = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot_id},
        headers={"Authorization": f"Bearer {client1_token}"},
    )
    assert r1.status_code == 201

    # Client 2 tente de réserver le même créneau
    r2 = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot_id},
        headers={"Authorization": f"Bearer {client2_token}"},
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_cancel_reservation_releases_slot(client: AsyncClient):
    """Annuler une réservation slot-based remet le créneau à AVAILABLE."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671004006"})
    client_token = await _register_and_token(client, {**CLIENT_PAYLOAD, "phone": "+22671004007"})
    terrain = await _create_terrain(client, owner_token)

    slot_resp = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots",
        json=_future_slot(offset_hours=5),
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    slot_id = slot_resp.json()["id"]
    slot_start = slot_resp.json()["start_datetime"]
    slot_end = slot_resp.json()["end_datetime"]

    # Réservation
    res_resp = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot_id},
        headers={"Authorization": f"Bearer {client_token}"},
    )
    reservation_id = res_resp.json()["id"]

    # Annulation
    cancel = await client.patch(
        f"/api/v1/reservations/{reservation_id}/cancel",
        headers={"Authorization": f"Bearer {client_token}"},
    )
    assert cancel.status_code == 200

    # Le créneau est de nouveau disponible
    check = await client.get(
        f"/api/v1/terrains/{terrain['id']}/availability",
        params={"start_datetime": slot_start, "end_datetime": slot_end},
    )
    assert check.json()["available"] is True


@pytest.mark.asyncio
async def test_list_available_slots(client: AsyncClient):
    """Liste les créneaux AVAILABLE sur une plage de dates."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671005001"})
    terrain = await _create_terrain(client, owner_token)

    now = datetime.now(timezone.utc)
    days_ahead = (7 - now.weekday()) % 7 or 7
    target = (now + timedelta(days=days_ahead + 14)).date()

    # Générer 1 jour de créneaux
    await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots/generate",
        json={
            "date_from": target.isoformat(),
            "date_to": target.isoformat(),
            "duration_minutes": 60,
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    resp = await client.get(
        f"/api/v1/terrains/{terrain['id']}/slots",
        params={"date_from": target.isoformat(), "date_to": target.isoformat()},
    )
    assert resp.status_code == 200
    slots = resp.json()
    assert len(slots) > 0
    assert all(s["status"] == "available" for s in slots)
    assert all(s["duration_minutes"] == 60 for s in slots)


@pytest.mark.asyncio
async def test_delete_available_slot(client: AsyncClient):
    """Un propriétaire peut supprimer un créneau AVAILABLE."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671006001"})
    terrain = await _create_terrain(client, owner_token)

    slot_resp = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots",
        json=_future_slot(offset_hours=6),
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    slot_id = slot_resp.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/terrains/{terrain['id']}/slots/{slot_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_cannot_delete_booked_slot(client: AsyncClient):
    """Impossible de supprimer un créneau déjà BOOKED."""
    owner_token = await _register_and_token(client, {**OWNER_PAYLOAD, "phone": "+22671006002"})
    client_token = await _register_and_token(client, {**CLIENT_PAYLOAD, "phone": "+22671006003"})
    terrain = await _create_terrain(client, owner_token)

    slot_resp = await client.post(
        f"/api/v1/terrains/{terrain['id']}/slots",
        json=_future_slot(offset_hours=7),
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    slot_id = slot_resp.json()["id"]

    await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot_id},
        headers={"Authorization": f"Bearer {client_token}"},
    )

    del_resp = await client.delete(
        f"/api/v1/terrains/{terrain['id']}/slots/{slot_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert del_resp.status_code == 400
