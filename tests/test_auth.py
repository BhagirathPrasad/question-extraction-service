import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_register_user(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "password": "strongpassword123",
            "full_name": "Test User"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "test@example.com"

@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    payload = {
        "email": "dup@example.com",
        "password": "strongpassword123"
    }
    await client.post("/auth/register", json=payload)
    response2 = await client.post("/auth/register", json=payload)
    assert response2.status_code == 409

@pytest.mark.asyncio
async def test_login_user(client: AsyncClient):
    payload = {
        "email": "login@example.com",
        "password": "strongpassword123"
    }
    await client.post("/auth/register", json=payload)
    
    response = await client.post("/auth/login", json=payload)
    assert response.status_code == 200
    assert "access_token" in response.json()

@pytest.mark.asyncio
async def test_get_me(client: AsyncClient):
    payload = {
        "email": "me@example.com",
        "password": "strongpassword123",
        "full_name": "Me User"
    }
    reg_response = await client.post("/auth/register", json=payload)
    token = reg_response.json()["access_token"]
    
    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Me User"
