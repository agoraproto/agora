"""Smoke tests for health endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from agora_api.main import app


@pytest.mark.asyncio
async def test_liveness() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_capabilities_static_tree() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert "capabilities" in body
    types = [c["name"] for c in body["capabilities"]]
    assert "Translation" in types
    assert "Verification" in types
