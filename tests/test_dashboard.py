"""
Tests du module Dashboard client GestFive.

Couvre :
- Dashboard vide (zéros partout, pas d'erreur)
- Prochaines réservations (triées par date, filtre PENDING/CONFIRMED)
- Historique (annulées + passées, COMPLETED exclus des upcoming)
- Statistiques agrégées (total, heures jouées sur COMPLETED, montant dépensé)
- Terrain préféré (plus de réservations non-annulées)
- Statistiques mensuelles (regroupement année/mois, libellé français)
- Pagination de l'historique
- Contrôle d'accès (401 sans token)
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

# ── Données de base ────────────────────────────────────────────────────────────

_OWNER = {
    "firstname": "Kofi",
    "lastname": "Mensah",
    "phone": "+22681000001",
    "password": "owner1234",
    "role": "owner",
}

_CLIENT = {
    "firstname": "Aya",
    "lastname": "Diallo",
    "phone": "+22681000002",
    "password": "client1234",
    "role": "client",
}

_TERRAIN_BODY = {
    "name": "Terrain Dashboard Test",
    "address": "Zone C, Ouaga",
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


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _register(client: AsyncClient, payload: dict) -> str:
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.json()
    return resp.json()["access_token"]


async def _create_terrain(
    client: AsyncClient, token: str, body: dict = _TERRAIN_BODY
) -> dict:
    resp = await client.post(
        "/api/v1/terrains/",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()


def _future_slot(hour: int = 10, duration_h: int = 1) -> dict:
    """Créneau futur un lundi dans les horaires 08-22."""
    now = datetime.now(timezone.utc)
    days_until_monday = (7 - now.weekday()) % 7 or 7
    monday = (now + timedelta(days=days_until_monday)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return {
        "start_datetime": monday.isoformat(),
        "end_datetime": (monday + timedelta(hours=duration_h)).isoformat(),
    }


async def _create_slot(
    client: AsyncClient, token: str, terrain_id: str, hour: int = 10, duration_h: int = 1
) -> dict:
    resp = await client.post(
        f"/api/v1/terrains/{terrain_id}/slots",
        json=_future_slot(hour=hour, duration_h=duration_h),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()


async def _book(
    client: AsyncClient, token: str, slot_id: str
) -> dict:
    resp = await client.post(
        "/api/v1/reservations/",
        json={"time_slot_id": slot_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()


async def _cancel(client: AsyncClient, token: str, reservation_id: str) -> None:
    resp = await client.patch(
        f"/api/v1/reservations/{reservation_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.json()


async def _set_status(
    client: AsyncClient, token: str, reservation_id: str, status: str
) -> dict:
    resp = await client.patch(
        f"/api/v1/reservations/{reservation_id}/status",
        json={"status": status},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_empty(client: AsyncClient):
    """Nouveau joueur sans réservations : dashboard renvoie zéros, pas d'erreur."""
    tok = await _register(client, {**_CLIENT, "phone": "+22681100001"})

    resp = await client.get(
        "/api/v1/dashboard/me",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["upcoming_reservations"] == []
    assert data["stats"]["total_reservations"] == 0
    assert data["stats"]["total_hours_played"] == 0
    assert data["stats"]["total_spent"] == 0
    assert data["favorite_terrain"] is None
    assert data["monthly_stats"] == []


@pytest.mark.asyncio
async def test_dashboard_requires_auth(client: AsyncClient):
    """Sans token → 401 sur tous les endpoints dashboard."""
    for path in ["/me", "/me/upcoming", "/me/history"]:
        resp = await client.get(f"/api/v1/dashboard{path}")
        assert resp.status_code == 401, f"{path} devrait être protégé"


@pytest.mark.asyncio
async def test_upcoming_sorted_by_date(client: AsyncClient):
    """Prochaines réservations triées par date croissante."""
    owner_tok = await _register(client, {**_OWNER, "phone": "+22681200001"})
    client_tok = await _register(client, {**_CLIENT, "phone": "+22681200002"})
    terrain = await _create_terrain(client, owner_tok)

    # 3 créneaux à 12h, 10h, 14h — doivent revenir triés : 10, 12, 14
    s10 = await _create_slot(client, owner_tok, terrain["id"], hour=10)
    s12 = await _create_slot(client, owner_tok, terrain["id"], hour=12)
    s14 = await _create_slot(client, owner_tok, terrain["id"], hour=14)
    await _book(client, client_tok, s12["id"])
    await _book(client, client_tok, s10["id"])
    await _book(client, client_tok, s14["id"])

    resp = await client.get(
        "/api/v1/dashboard/me/upcoming",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 3
    dates = [i["start_datetime"] for i in items]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_upcoming_excludes_cancelled(client: AsyncClient):
    """Une réservation annulée ne doit PAS apparaître dans les upcoming."""
    owner_tok = await _register(client, {**_OWNER, "phone": "+22681300001"})
    client_tok = await _register(client, {**_CLIENT, "phone": "+22681300002"})
    terrain = await _create_terrain(client, owner_tok)

    slot = await _create_slot(client, owner_tok, terrain["id"], hour=10)
    res = await _book(client, client_tok, slot["id"])
    await _cancel(client, client_tok, res["id"])

    resp = await client.get(
        "/api/v1/dashboard/me/upcoming",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_upcoming_limit_param(client: AsyncClient):
    """Le paramètre ?limit limite le nombre de résultats."""
    owner_tok = await _register(client, {**_OWNER, "phone": "+22681400001"})
    client_tok = await _register(client, {**_CLIENT, "phone": "+22681400002"})
    terrain = await _create_terrain(client, owner_tok)

    for hour in [10, 12, 14, 16]:
        s = await _create_slot(client, owner_tok, terrain["id"], hour=hour)
        await _book(client, client_tok, s["id"])

    resp = await client.get(
        "/api/v1/dashboard/me/upcoming?limit=2",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_history_contains_cancelled(client: AsyncClient):
    """Une réservation annulée (future) doit apparaître dans l'historique."""
    owner_tok = await _register(client, {**_OWNER, "phone": "+22681500001"})
    client_tok = await _register(client, {**_CLIENT, "phone": "+22681500002"})
    terrain = await _create_terrain(client, owner_tok)

    slot = await _create_slot(client, owner_tok, terrain["id"], hour=10)
    res = await _book(client, client_tok, slot["id"])
    await _cancel(client, client_tok, res["id"])

    resp = await client.get(
        "/api/v1/dashboard/me/history",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == res["id"]
    assert data["items"][0]["status"] == "cancelled"
    assert data["items"][0]["terrain_name"] == terrain["name"]


@pytest.mark.asyncio
async def test_history_pagination(client: AsyncClient):
    """skip/limit fonctionnent correctement sur l'historique."""
    owner_tok = await _register(client, {**_OWNER, "phone": "+22681600001"})
    client_tok = await _register(client, {**_CLIENT, "phone": "+22681600002"})
    terrain = await _create_terrain(client, owner_tok)

    # Créer 3 réservations et les annuler → 3 entrées dans l'historique
    for hour in [10, 12, 14]:
        s = await _create_slot(client, owner_tok, terrain["id"], hour=hour)
        r = await _book(client, client_tok, s["id"])
        await _cancel(client, client_tok, r["id"])

    page1 = await client.get(
        "/api/v1/dashboard/me/history?skip=0&limit=2",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert page1.status_code == 200
    d1 = page1.json()
    assert d1["total"] == 3
    assert len(d1["items"]) == 2
    assert d1["has_more"] is True

    page2 = await client.get(
        "/api/v1/dashboard/me/history?skip=2&limit=2",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    d2 = page2.json()
    assert len(d2["items"]) == 1
    assert d2["has_more"] is False


@pytest.mark.asyncio
async def test_stats_aggregate(client: AsyncClient):
    """
    Scénario complet :
    - 2 PENDING (actives)
    - 1 CANCELLED → pas dans total_hours ni total_spent non
    - 1 COMPLETED 1h → total_hours = 1.0
    """
    owner_tok = await _register(client, {**_OWNER, "phone": "+22681700001"})
    client_tok = await _register(client, {**_CLIENT, "phone": "+22681700002"})
    terrain = await _create_terrain(client, owner_tok)

    s1 = await _create_slot(client, owner_tok, terrain["id"], hour=10)
    s2 = await _create_slot(client, owner_tok, terrain["id"], hour=12)
    s3 = await _create_slot(client, owner_tok, terrain["id"], hour=14)
    s4 = await _create_slot(client, owner_tok, terrain["id"], hour=16)

    await _book(client, client_tok, s1["id"])  # PENDING
    await _book(client, client_tok, s2["id"])  # PENDING
    r3 = await _book(client, client_tok, s3["id"])
    await _cancel(client, client_tok, r3["id"])  # CANCELLED
    r4 = await _book(client, client_tok, s4["id"])
    await _set_status(client, owner_tok, r4["id"], "completed")  # COMPLETED 1h

    resp = await client.get(
        "/api/v1/dashboard/me",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert stats["total_reservations"] == 4
    assert stats["completed_reservations"] == 1
    assert stats["cancelled_reservations"] == 1
    assert stats["active_reservations"] == 2
    # 1h COMPLETED × price_per_hour=10 → total_hours=1.0, total_spent include toutes sauf?
    # total_spent = SUM(total_price) de toutes les réservations y compris annulée
    assert stats["total_hours_played"] == pytest.approx(1.0)
    assert stats["total_spent"] == pytest.approx(40.0)  # 4 × 10.0


@pytest.mark.asyncio
async def test_favorite_terrain(client: AsyncClient):
    """Le terrain avec le plus de réservations non-annulées est le préféré."""
    owner_tok = await _register(client, {**_OWNER, "phone": "+22681800001"})
    client_tok = await _register(client, {**_CLIENT, "phone": "+22681800002"})

    terrain1 = await _create_terrain(
        client, owner_tok, {**_TERRAIN_BODY, "name": "Terrain Fav A"}
    )
    terrain2 = await _create_terrain(
        client, owner_tok, {**_TERRAIN_BODY, "name": "Terrain Fav B"}
    )

    # terrain1 : 3 réservations PENDING (non-annulées)
    for hour in [10, 12, 14]:
        s = await _create_slot(client, owner_tok, terrain1["id"], hour=hour)
        await _book(client, client_tok, s["id"])

    # terrain2 : 1 réservation PENDING + 1 CANCELLED
    s = await _create_slot(client, owner_tok, terrain2["id"], hour=10)
    await _book(client, client_tok, s["id"])
    s2 = await _create_slot(client, owner_tok, terrain2["id"], hour=12)
    r2 = await _book(client, client_tok, s2["id"])
    await _cancel(client, client_tok, r2["id"])

    resp = await client.get(
        "/api/v1/dashboard/me",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 200
    fav = resp.json()["favorite_terrain"]
    assert fav is not None
    assert fav["terrain_id"] == terrain1["id"]
    assert fav["terrain_name"] == "Terrain Fav A"
    assert fav["booking_count"] == 3


@pytest.mark.asyncio
async def test_monthly_stats_structure(client: AsyncClient):
    """Les stats mensuelles ont la bonne structure et le bon libellé en français."""
    owner_tok = await _register(client, {**_OWNER, "phone": "+22681900001"})
    client_tok = await _register(client, {**_CLIENT, "phone": "+22681900002"})
    terrain = await _create_terrain(client, owner_tok)

    slot = await _create_slot(client, owner_tok, terrain["id"], hour=10, duration_h=2)
    await _book(client, client_tok, slot["id"])

    resp = await client.get(
        "/api/v1/dashboard/me",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 200
    monthly = resp.json()["monthly_stats"]
    assert len(monthly) >= 1

    entry = monthly[0]
    assert "year" in entry
    assert "month" in entry
    assert "month_label" in entry
    assert "reservations_count" in entry
    assert "total_hours" in entry
    assert "total_spent" in entry

    # Libellé : "Mois YYYY", le séparateur est un espace
    assert str(entry["year"]) in entry["month_label"]

    # Réservation de 2h à 10€/h → total_hours=2.0, total_spent=20.0
    assert entry["reservations_count"] == 1
    assert entry["total_hours"] == pytest.approx(2.0)
    assert entry["total_spent"] == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_monthly_stats_excludes_cancelled(client: AsyncClient):
    """Une réservation annulée ne compte pas dans les stats mensuelles."""
    owner_tok = await _register(client, {**_OWNER, "phone": "+22682000001"})
    client_tok = await _register(client, {**_CLIENT, "phone": "+22682000002"})
    terrain = await _create_terrain(client, owner_tok)

    s1 = await _create_slot(client, owner_tok, terrain["id"], hour=10)
    await _book(client, client_tok, s1["id"])  # PENDING → comptée

    s2 = await _create_slot(client, owner_tok, terrain["id"], hour=12)
    r2 = await _book(client, client_tok, s2["id"])
    await _cancel(client, client_tok, r2["id"])  # CANCELLED → non comptée

    resp = await client.get(
        "/api/v1/dashboard/me",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 200
    monthly = resp.json()["monthly_stats"]
    assert len(monthly) == 1
    assert monthly[0]["reservations_count"] == 1


@pytest.mark.asyncio
async def test_dashboard_includes_terrain_name(client: AsyncClient):
    """Les upcoming et l'historique incluent le nom et la ville du terrain."""
    owner_tok = await _register(client, {**_OWNER, "phone": "+22682100001"})
    client_tok = await _register(client, {**_CLIENT, "phone": "+22682100002"})
    terrain = await _create_terrain(
        client, owner_tok, {**_TERRAIN_BODY, "name": "Terrain Visible"}
    )

    slot = await _create_slot(client, owner_tok, terrain["id"], hour=10)
    res = await _book(client, client_tok, slot["id"])

    # upcoming doit inclure terrain_name
    resp = await client.get(
        "/api/v1/dashboard/me/upcoming",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["terrain_name"] == "Terrain Visible"
    assert item["terrain_city"] == "Ouagadougou"
    assert item["duration_minutes"] == 60

    # history après annulation
    await _cancel(client, client_tok, res["id"])
    resp2 = await client.get(
        "/api/v1/dashboard/me/history",
        headers={"Authorization": f"Bearer {client_tok}"},
    )
    hist_item = resp2.json()["items"][0]
    assert hist_item["terrain_name"] == "Terrain Visible"
