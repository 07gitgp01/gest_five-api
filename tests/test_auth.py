import pytest
from httpx import AsyncClient

REGISTER_PAYLOAD = {
    "firstname": "Moussa",
    "lastname": "Traoré",
    "phone": "+22670000001",
    "email": "moussa@gestfive.com",
    "password": "secret123",
    "role": "client",
}


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    response = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_phone(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    response = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient):
    payload = {**REGISTER_PAYLOAD, "phone": "+22670000099", "password": "short"}
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    payload = {**REGISTER_PAYLOAD, "phone": "+22670000002"}
    await client.post("/api/v1/auth/register", json=payload)
    response = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+22670000002", "password": "secret123"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    payload = {**REGISTER_PAYLOAD, "phone": "+22670000003"}
    await client.post("/api/v1/auth/register", json=payload)
    response = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+22670000003", "password": "wrongpass"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_phone(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+00000000000", "password": "doesnotmatter1"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_tokens(client: AsyncClient):
    payload = {**REGISTER_PAYLOAD, "phone": "+22670000004"}
    reg = await client.post("/api/v1/auth/register", json=payload)
    refresh_token = reg.json()["refresh_token"]

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient):
    payload = {**REGISTER_PAYLOAD, "phone": "+22670000005"}
    reg = await client.post("/api/v1/auth/register", json=payload)
    token = reg.json()["access_token"]

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["phone"] == "+22670000005"
    assert data["firstname"] == "Moussa"
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_change_password(client: AsyncClient):
    payload = {**REGISTER_PAYLOAD, "phone": "+22670000006"}
    reg = await client.post("/api/v1/auth/register", json=payload)
    token = reg.json()["access_token"]

    response = await client.post(
        "/api/v1/users/me/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "secret123", "new_password": "newsecret456"},
    )
    assert response.status_code == 204

    # Ancien token toujours valide (stateless JWT), mais le nouveau mot de passe fonctionne
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+22670000006", "password": "newsecret456"},
    )
    assert login_resp.status_code == 200


@pytest.mark.asyncio
async def test_deactivate_me(client: AsyncClient):
    payload = {**REGISTER_PAYLOAD, "phone": "+22670000007"}
    reg = await client.post("/api/v1/auth/register", json=payload)
    token = reg.json()["access_token"]

    response = await client.delete(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204

    # Le login doit échouer après désactivation
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"phone": "+22670000007", "password": "secret123"},
    )
    assert login_resp.status_code == 401
