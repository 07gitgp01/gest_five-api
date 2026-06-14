"""
Tests du module Administration GestFive.

Couvre :
- Contrôle d'accès : client/owner → 403, sans token → 401
- Liste et recherche des utilisateurs (texte, rôle, is_active)
- Blocage / déblocage utilisateur
- Changement de rôle
- Impossibilité de s'auto-bloquer ou de changer son propre rôle
- Liste terrains avec filtre par statut
- Validation d'un terrain (→ ACTIVE + notification)
- Suspension d'un terrain (→ INACTIVE + notification)
- Statistiques plateforme (structure + cohérence des compteurs)
- Rapport de croissance (structure + libellés français)
"""

import pytest
from httpx import AsyncClient

# ── Données de base ────────────────────────────────────────────────────────────

_ADMIN = {
    "firstname": "Admin",
    "lastname": "Central",
    "phone": "+22600100001",
    "password": "admin1234",
    "role": "admin",
}
_OWNER = {
    "firstname": "Boubacar",
    "lastname": "Diallo",
    "phone": "+22600100002",
    "password": "owner1234",
    "role": "owner",
}
_CLIENT = {
    "firstname": "Rokia",
    "lastname": "Coulibaly",
    "phone": "+22600100003",
    "password": "client1234",
    "role": "client",
}
_TERRAIN_BODY = {
    "name": "Terrain Admin Test",
    "address": "Zone F, Ouaga",
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


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _reg(client: AsyncClient, payload: dict) -> str:
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.json()
    return r.json()["access_token"]


async def _reg_full(client: AsyncClient, payload: dict) -> dict:
    """Inscrit un utilisateur et retourne son access_token + son profil (via /users/me)."""
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201, r.json()
    tok = r.json()["access_token"]
    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200, me.json()
    return {"access_token": tok, "user": me.json()}


async def _terrain(client: AsyncClient, tok: str) -> dict:
    r = await client.post(
        "/api/v1/terrains/",
        json=_TERRAIN_BODY,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 201, r.json()
    return r.json()


# ── Contrôle d'accès ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_endpoints_require_auth(client: AsyncClient):
    """Sans token → 401 sur les endpoints admin."""
    for path in ["/users", "/terrains", "/stats", "/stats/growth"]:
        r = await client.get(f"/api/v1/admin{path}")
        assert r.status_code == 401, f"{path} doit être protégé"


@pytest.mark.asyncio
async def test_admin_endpoints_require_admin_role(client: AsyncClient):
    """Client et owner → 403 sur tous les endpoints admin."""
    client_tok = await _reg(client, {**_CLIENT, "phone": "+22601100001"})
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22601100002"})

    for tok in [client_tok, owner_tok]:
        r = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 403


# ── Gestion des utilisateurs ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_all_users(client: AsyncClient):
    """L'admin voit tous les utilisateurs inscrits."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22602100001"})
    await _reg(client, {**_CLIENT, "phone": "+22602100002"})
    await _reg(client, {**_OWNER, "phone": "+22602100003"})

    r = await client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 3
    assert "items" in data


@pytest.mark.asyncio
async def test_search_users_by_name(client: AsyncClient):
    """?q=Rokia filtre par prénom."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22603100001"})
    await _reg(client, {**_CLIENT, "phone": "+22603100002"})

    r = await client.get(
        "/api/v1/admin/users?q=Rokia",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert all("Rokia" in i["firstname"] or "Rokia" in i["lastname"] for i in items)


@pytest.mark.asyncio
async def test_filter_users_by_role(client: AsyncClient):
    """?role=owner retourne seulement les propriétaires."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22604100001"})
    await _reg(client, {**_OWNER, "phone": "+22604100002"})
    await _reg(client, {**_CLIENT, "phone": "+22604100003"})

    r = await client.get(
        "/api/v1/admin/users?role=owner",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["role"] == "owner" for i in items)
    assert len(items) >= 1


@pytest.mark.asyncio
async def test_filter_users_by_is_active(client: AsyncClient):
    """?is_active=true filtre les comptes actifs."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22605100001"})
    user_data = await _reg_full(client, {**_CLIENT, "phone": "+22605100002"})
    user_id = user_data["user"]["id"]

    # Bloquer le client
    await client.patch(
        f"/api/v1/admin/users/{user_id}/block",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )

    # is_active=false → doit contenir le client bloqué
    r = await client.get(
        "/api/v1/admin/users?is_active=false",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert user_id in ids


@pytest.mark.asyncio
async def test_block_and_unblock_user(client: AsyncClient):
    """PATCH /block bascule is_active. Deux appels = re-activé."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22606100001"})
    user_data = await _reg_full(client, {**_CLIENT, "phone": "+22606100002"})
    user_id = user_data["user"]["id"]

    # Bloquer
    r1 = await client.patch(
        f"/api/v1/admin/users/{user_id}/block",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r1.status_code == 200
    assert r1.json()["is_active"] is False

    # Débloquer
    r2 = await client.patch(
        f"/api/v1/admin/users/{user_id}/block",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r2.json()["is_active"] is True


@pytest.mark.asyncio
async def test_cannot_block_self(client: AsyncClient):
    """Un admin ne peut pas bloquer son propre compte → 400."""
    admin_data = await _reg_full(client, {**_ADMIN, "phone": "+22607100001"})
    admin_tok = admin_data["access_token"]
    admin_id = admin_data["user"]["id"]

    r = await client.patch(
        f"/api/v1/admin/users/{admin_id}/block",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_change_user_role(client: AsyncClient):
    """PATCH /role change le rôle d'un utilisateur."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22608100001"})
    user_data = await _reg_full(client, {**_CLIENT, "phone": "+22608100002"})
    user_id = user_data["user"]["id"]

    r = await client.patch(
        f"/api/v1/admin/users/{user_id}/role",
        json={"role": "owner"},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "owner"


@pytest.mark.asyncio
async def test_cannot_change_own_role(client: AsyncClient):
    """Un admin ne peut pas modifier son propre rôle → 400."""
    admin_data = await _reg_full(client, {**_ADMIN, "phone": "+22609100001"})
    admin_tok = admin_data["access_token"]
    admin_id = admin_data["user"]["id"]

    r = await client.patch(
        f"/api/v1/admin/users/{admin_id}/role",
        json={"role": "client"},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_user_detail(client: AsyncClient):
    """GET /users/{id} retourne les détails complets d'un utilisateur."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22610100001"})
    user_data = await _reg_full(client, {**_CLIENT, "phone": "+22610100002"})
    user_id = user_data["user"]["id"]

    r = await client.get(
        f"/api/v1/admin/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == user_id
    assert "role" in data
    assert "is_active" in data


# ── Gestion des terrains ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_all_terrains(client: AsyncClient):
    """L'admin voit tous les terrains, quel que soit leur statut."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22611100001"})
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22611100002"})
    t = await _terrain(client, owner_tok)

    r = await client.get(
        "/api/v1/admin/terrains",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    data = r.json()
    ids = [i["id"] for i in data["items"]]
    assert t["id"] in ids


@pytest.mark.asyncio
async def test_filter_terrains_by_status(client: AsyncClient):
    """?status=active filtre par statut."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22612100001"})
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22612100002"})
    t = await _terrain(client, owner_tok)

    # Valider le terrain → ACTIVE
    await client.patch(
        f"/api/v1/admin/terrains/{t['id']}/validate",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )

    r = await client.get(
        "/api/v1/admin/terrains?status=active",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["status"] == "active" for i in items)


@pytest.mark.asyncio
async def test_validate_terrain(client: AsyncClient):
    """PATCH /validate → statut ACTIVE, terrain visible dans la liste active."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22613100001"})
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22613100002"})
    t = await _terrain(client, owner_tok)

    r = await client.patch(
        f"/api/v1/admin/terrains/{t['id']}/validate",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "active"
    assert data["owner_name"] != ""  # nom du propriétaire inclus


@pytest.mark.asyncio
async def test_suspend_terrain(client: AsyncClient):
    """PATCH /suspend → statut INACTIVE + motif transmis dans la réponse."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22614100001"})
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22614100002"})
    t = await _terrain(client, owner_tok)

    r = await client.patch(
        f"/api/v1/admin/terrains/{t['id']}/suspend",
        json={"reason": "Non-conformité aux règles de la plateforme"},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "inactive"


@pytest.mark.asyncio
async def test_validate_then_suspend(client: AsyncClient):
    """Valider puis suspendre fonctionne correctement."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22615100001"})
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22615100002"})
    t = await _terrain(client, owner_tok)

    await client.patch(
        f"/api/v1/admin/terrains/{t['id']}/validate",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    r = await client.patch(
        f"/api/v1/admin/terrains/{t['id']}/suspend",
        json={"reason": "Maintenance"},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.json()["status"] == "inactive"


# ── Statistiques ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_platform_stats_structure(client: AsyncClient):
    """GET /stats retourne la structure complète avec toutes les clés."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22616100001"})

    r = await client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    data = r.json()

    assert "users" in data
    assert "terrains" in data
    assert "reservations" in data
    assert "revenue" in data

    for key in ["total", "active", "inactive", "clients", "owners", "admins", "new_this_month"]:
        assert key in data["users"], f"Clé manquante dans users : {key}"

    for key in ["total", "active", "inactive", "maintenance"]:
        assert key in data["terrains"], f"Clé manquante dans terrains : {key}"

    for key in ["total", "pending", "confirmed", "completed", "cancelled"]:
        assert key in data["reservations"], f"Clé manquante dans reservations : {key}"

    for key in ["total_revenue", "month_revenue", "total_successful_payments"]:
        assert key in data["revenue"], f"Clé manquante dans revenue : {key}"


@pytest.mark.asyncio
async def test_platform_stats_counts(client: AsyncClient):
    """Les compteurs reflètent les données insérées."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22617100001"})
    await _reg(client, {**_OWNER, "phone": "+22617100002"})
    await _reg(client, {**_CLIENT, "phone": "+22617100003"})

    r = await client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    stats = r.json()
    # Au moins admin + owner + client créés
    assert stats["users"]["total"] >= 3
    assert stats["users"]["admins"] >= 1
    assert stats["users"]["owners"] >= 1
    assert stats["users"]["clients"] >= 1
    # Invariant : total = active + inactive
    assert (
        stats["users"]["active"] + stats["users"]["inactive"]
        == stats["users"]["total"]
    )
    assert (
        stats["terrains"]["active"]
        + stats["terrains"]["inactive"]
        + stats["terrains"]["maintenance"]
        == stats["terrains"]["total"]
    )


@pytest.mark.asyncio
async def test_growth_report_structure(client: AsyncClient):
    """GET /stats/growth retourne la bonne structure."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22618100001"})
    # Créer un owner pour avoir au moins un terrain
    owner_tok = await _reg(client, {**_OWNER, "phone": "+22618100002"})
    await _terrain(client, owner_tok)

    r = await client.get(
        "/api/v1/admin/stats/growth",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    data = r.json()

    assert "data" in data
    assert "users_growth_pct" in data
    assert "revenue_growth_pct" in data

    if data["data"]:
        entry = data["data"][0]
        for key in ["year", "month", "month_label", "new_users", "new_terrains", "reservations", "revenue"]:
            assert key in entry, f"Clé manquante : {key}"
        # Libellé contient l'année
        assert str(entry["year"]) in entry["month_label"]


@pytest.mark.asyncio
async def test_growth_report_months_param(client: AsyncClient):
    """?months=3 limite la fenêtre d'analyse."""
    admin_tok = await _reg(client, {**_ADMIN, "phone": "+22619100001"})

    r = await client.get(
        "/api/v1/admin/stats/growth?months=3",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 200
    # La fenêtre de 3 mois ne doit pas retourner plus de 3 entrées
    assert len(r.json()["data"]) <= 3
