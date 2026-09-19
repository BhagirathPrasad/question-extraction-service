import pytest
from httpx import AsyncClient

@pytest.fixture
async def auth_token(client: AsyncClient) -> str:
    response = await client.post(
        "/auth/register",
        json={"email": "doc@example.com", "password": "password123"}
    )
    return response.json()["access_token"]

@pytest.mark.asyncio
async def test_list_documents_empty(client: AsyncClient, auth_token: str):
    response = await client.get(
        "/documents/",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
async def test_upload_invalid_file_type(client: AsyncClient, auth_token: str):
    files = {"file": ("test.txt", b"dummy content", "text/plain")}
    response = await client.post(
        "/documents/upload",
        files=files,
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 415
    assert "not supported" in response.json()["detail"]
