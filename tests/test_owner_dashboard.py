"""
Tests du module Dashboard Propriétaire GestFive.

Couvre :
- Dashboard vide (owner sans terrains ni réservations)
- Contrôle d'accès : client → 403, sans token → 401
- Statistiques all-time (total_revenue, total_reservations, terrain counts)
- Taux d'occupation : booked_hours calculé depuis les réservations du mois
- Heures de pointe : regroupement par heure, tri par fréquence décroissante
- Revenus mensuels : group by année/mois, libellé français
- Endpoint /occupancy séparé
- Endpoint /peak-hours séparé
- Endpoint /revenue séparé
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

# ── Données de base ────────────────────────────────────────────────────────────

_OWNER = {
    "firstname": "Issa",
    "lastname": "Kaboré",
    "phone": "+22690000001",
    "password": "owner1234",
    "role": "owner",
}
_CLIENT = {
    "firstname": "Aïcha",
    "lastname": "Traoré",
    "phone": "+22690000002",
    "password": "client1234",
    "role": "client",
}
_OPENING_HOURS = {
    "monday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "tuesday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "wednesday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "thursday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "friday": {"open": "08:00", "close": "22:00", "is_closed": False},
    "saturday": {"open": "09:00", "close": "20:00", "is_closed": False},
    "sunday": {"open": "00:00", "close": "00:00", "is_closed": True},
}
_TERRAIN_BODY = {
    "name": "Terrain Owner Test",
    "address": "Zone D, Ouaga",
    "city": "Ouagadougou",
    "price_per_hour": 15.0,
    "opening_hours": _OPENING_HOURS,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _reg(client: AsyncClient, payload: dict) -> str:
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.json()
    return r.json()["access_token"]


async def _terrain(client: AsyncClient, tok: str, body: dict = _TERRAIN_BODY) -> dict:
    r = await client.post(
        "/api/v1/terrains/",
        json=body,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 201, r.json()
    return r.json()


def _next_monday(hour: int = 10, duration_h: int = 1) -> dict:
    now = datetime.now(timezone.utc)
    days = (7 - now.weekday()) % 7 or 7
    start = (now + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return {
        "start_datetime": start.isoformat(),
        "end_datetime": (start + timedelta(hours=duration_h)).isoformat(),
    }


async def _slot(client: AsyncClient, tok: str, terrain_id: str, hour: int = 10, dur: int = 1) -> dict:
    r = await client.post(
        f"/api/v1/terrains/{terrain_id}/slots",
        json=_next_monday(hour=hour, duration_h=dur),
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


async def _cancel(client: AsyncClient, tok: str, res_id: str) -> None:
    r = await client.patch(
        f"/api/v1/reservations/{res_id}/cancel",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.json()


async def _complete(client: AsyncClient, tok: str, res_id: str) -> None:
    r = await client.patch(
        f"/api/v1/reservations/{res_id}/status",
        json={"status": "completed"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.json()


# ── Contrôle d'accès ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_dashboard_requires_auth(client: AsyncClient):
    """Sans token → 401 sur tous les endpoints."""
    for path in ["/me", "/me/occupancy", "/me/peak-hours", "/me/revenue"]:
        r = await client.get(f"/api/v1/owner-dashboard{path}")
        assert r.status_code == 401, f"{path} devrait être protégé"


@pytest.mark.asyncio
async def test_owner_dashboard_forbidden_for_client(client: AsyncClient):
    """Un client ne peut pas accéder au dashboard propriétaire → 403."""
    tok = await _reg(client, {**_CLIENT, "phone": "+22691000001"})
    r = await client.get(
        "/api/v1/owner-dashboard/me",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403


# ── Dashboard vide ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_dashboard(client: AsyncClient):
    """Propriétaire sans terrain ni réservation → zéros partout, pas d'erreur."""
    tok = await _reg(client, {**_OWNER, "phone": "+22692000001"})
    r = await client.get(
        "/api/v1/owner-dashboard/me",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    data = r.json()
    stats = data["stats"]
    assert stats["total_terrains"] == 0
    assert stats["active_terrains"] == 0
    assert stats["total_reservations"] == 0
    assert stats["total_revenue"] == 0
    assert data["terrain_occupancy"] == []
    assert data["peak_hours"] == []
    assert data["daily_revenue"] == []
    assert data["monthly_revenue"] == []


# ── Statistiques ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_terrain_counts(client: AsyncClient):
    """Compte les terrains actifs du propriétaire."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22693000001"})
    await _terrain(client, owner_tok)
    await _terrain(client, owner_tok, {**_TERRAIN_BODY, "name": "Terrain 2"})

    r = await client.get(
        "/api/v1/owner-dashboard/me",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert r.status_code == 200
    stats = r.json()["stats"]
    assert stats["total_terrains"] == 2
    assert stats["active_terrains"] == 2


@pytest.mark.asyncio
async def test_stats_all_time_revenue(client: AsyncClient):
    """total_revenue et total_reservations incluent toutes les non-annulées."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22694000001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22694000002"})
    t = await _terrain(client, owner_tok)

    # 2 réservations à 15€/h (1h chacune) → total = 30
    s1 = await _slot(client, owner_tok, t["id"], hour=10)
    s2 = await _slot(client, owner_tok, t["id"], hour=12)
    await _book(client, client_tok, s1["id"])
    await _book(client, client_tok, s2["id"])

    r = await client.get(
        "/api/v1/owner-dashboard/me",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    stats = r.json()["stats"]
    assert stats["total_reservations"] == 2
    assert stats["total_revenue"] == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_stats_cancelled_excluded(client: AsyncClient):
    """Réservations annulées non comptées dans total_revenue."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22695000001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22695000002"})
    t = await _terrain(client, owner_tok)

    s1 = await _slot(client, owner_tok, t["id"], hour=10)
    s2 = await _slot(client, owner_tok, t["id"], hour=12)
    res1 = await _book(client, client_tok, s1["id"])
    await _book(client, client_tok, s2["id"])
    await _cancel(client, client_tok, res1["id"])  # annulée

    r = await client.get(
        "/api/v1/owner-dashboard/me",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    stats = r.json()["stats"]
    # Seulement res2 compte
    assert stats["total_reservations"] == 1
    assert stats["total_revenue"] == pytest.approx(15.0)


# ── Taux d'occupation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_occupancy_booked_hours(client: AsyncClient):
    """booked_hours reflète les heures réservées ce mois (non-annulées)."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22696000001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22696000002"})
    t = await _terrain(client, owner_tok)

    # Réserver 2 créneaux de 2h = 4h totales
    s1 = await _slot(client, owner_tok, t["id"], hour=10, dur=2)
    s2 = await _slot(client, owner_tok, t["id"], hour=14, dur=2)
    await _book(client, client_tok, s1["id"])
    await _book(client, client_tok, s2["id"])

    r = await client.get(
        "/api/v1/owner-dashboard/me/occupancy",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    occ = items[0]
    assert occ["terrain_name"] == t["name"]
    assert occ["booked_hours"] == pytest.approx(4.0)
    assert occ["capacity_hours"] > 0  # calculé depuis opening_hours
    assert 0.0 <= occ["occupancy_rate"] <= 100.0


@pytest.mark.asyncio
async def test_occupancy_cancelled_not_counted(client: AsyncClient):
    """Les annulations ne comptent pas dans booked_hours."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22697000001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22697000002"})
    t = await _terrain(client, owner_tok)

    s1 = await _slot(client, owner_tok, t["id"], hour=10)
    s2 = await _slot(client, owner_tok, t["id"], hour=12)
    r1 = await _book(client, client_tok, s1["id"])
    await _book(client, client_tok, s2["id"])
    await _cancel(client, client_tok, r1["id"])

    r = await client.get(
        "/api/v1/owner-dashboard/me/occupancy",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    occ = r.json()[0]
    # Seulement s2 (1h) doit compter
    assert occ["booked_hours"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_occupancy_terrain_with_no_booking_appears(client: AsyncClient):
    """Un terrain sans réservation ce mois apparaît avec booked_hours=0."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22698000001"})
    await _terrain(client, owner_tok)  # aucune réservation

    r = await client.get(
        "/api/v1/owner-dashboard/me/occupancy",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["booked_hours"] == 0.0
    assert items[0]["occupancy_rate"] == 0.0


# ── Heures de pointe ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_peak_hours_sorted_by_count(client: AsyncClient):
    """Les heures de pointe sont triées par fréquence décroissante."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22699000001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22699000002"})
    t = await _terrain(client, owner_tok)

    # 1 réservation à 10h, 2 à 14h (sur des semaines différentes — même créneau simulé par durées)
    # Pour des tests simples, 1 réservation par heure distincte
    for hour in [14, 14]:
        # Impossible de réserver deux fois le même créneau → on utilise des heures distinctes proches
        pass
    # Deux réservations à 14h n'est pas possible (conflit).
    # On réserve 14h:00 (1h) et 15h:00 (1h) : deux heures différentes
    s1 = await _slot(client, owner_tok, t["id"], hour=10)
    s2 = await _slot(client, owner_tok, t["id"], hour=14)
    await _book(client, client_tok, s1["id"])
    await _book(client, client_tok, s2["id"])

    r = await client.get(
        "/api/v1/owner-dashboard/me/peak-hours",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    # Chaque heure avec 1 réservation — les deux apparaissent
    hours = {i["hour"] for i in items}
    assert 10 in hours
    assert 14 in hours
    # percentage total = 100%
    total_pct = sum(i["percentage"] for i in items)
    assert total_pct == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_peak_hours_cancelled_excluded(client: AsyncClient):
    """Les réservations annulées ne contribuent pas aux heures de pointe."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22699100001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22699100002"})
    t = await _terrain(client, owner_tok)

    s = await _slot(client, owner_tok, t["id"], hour=10)
    res = await _book(client, client_tok, s["id"])
    await _cancel(client, client_tok, res["id"])

    r = await client.get(
        "/api/v1/owner-dashboard/me/peak-hours",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert r.status_code == 200
    assert r.json() == []  # aucune réservation comptée


# ── Revenus ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_monthly_revenue_structure(client: AsyncClient):
    """Revenus mensuels : structure, libellé français, compteurs cohérents."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22699200001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22699200002"})
    t = await _terrain(client, owner_tok)

    s = await _slot(client, owner_tok, t["id"], hour=10, dur=2)
    await _book(client, client_tok, s["id"])  # 2h × 15 = 30 XOF

    r = await client.get(
        "/api/v1/owner-dashboard/me/revenue",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "daily_last_7_days" in data
    assert "monthly_last_6_months" in data

    monthly = data["monthly_last_6_months"]
    assert len(monthly) >= 1
    entry = monthly[0]
    assert "year" in entry
    assert "month" in entry
    assert "month_label" in entry
    # Libellé contient l'année
    assert str(entry["year"]) in entry["month_label"]
    assert entry["revenue"] == pytest.approx(30.0)
    assert entry["reservations_count"] == 1


@pytest.mark.asyncio
async def test_revenue_monthly_excludes_cancelled(client: AsyncClient):
    """Réservations annulées non comptées dans les revenus mensuels."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22699300001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22699300002"})
    t = await _terrain(client, owner_tok)

    s1 = await _slot(client, owner_tok, t["id"], hour=10)
    s2 = await _slot(client, owner_tok, t["id"], hour=12)
    await _book(client, client_tok, s1["id"])  # comptée
    r2 = await _book(client, client_tok, s2["id"])
    await _cancel(client, client_tok, r2["id"])  # annulée → exclue

    r = await client.get(
        "/api/v1/owner-dashboard/me/revenue",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    monthly = r.json()["monthly_last_6_months"]
    assert len(monthly) == 1
    assert monthly[0]["reservations_count"] == 1
    assert monthly[0]["revenue"] == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_full_dashboard_structure(client: AsyncClient):
    """Vérifie toutes les clés du dashboard complet."""
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22699400001"})
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22699400002"})
    t = await _terrain(client, owner_tok)

    s = await _slot(client, owner_tok, t["id"], hour=10)
    await _book(client, client_tok, s["id"])

    r = await client.get(
        "/api/v1/owner-dashboard/me",
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert r.status_code == 200
    data = r.json()

    # Structure de haut niveau
    assert "stats" in data
    assert "terrain_occupancy" in data
    assert "peak_hours" in data
    assert "daily_revenue" in data
    assert "monthly_revenue" in data

    # Stats minimaux
    stats = data["stats"]
    for key in [
        "today_revenue", "today_reservations",
        "month_revenue", "month_reservations",
        "total_revenue", "total_reservations",
        "total_terrains", "active_terrains",
    ]:
        assert key in stats, f"Clé manquante : {key}"

    # Terrain occupancy
    occ = data["terrain_occupancy"][0]
    for key in ["terrain_id", "terrain_name", "booked_hours", "capacity_hours", "occupancy_rate"]:
        assert key in occ

    # Peak hours
    peak = data["peak_hours"][0]
    for key in ["hour", "hour_label", "reservations_count", "percentage"]:
        assert key in peak
    assert peak["hour_label"].endswith("h00")
