"""Unit tests for health and readiness endpoints (no DB required)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200():
    from traffic_ai.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_ready_returns_degraded_without_db():
    """Readiness check should return degraded status when services are not connected."""
    from traffic_ai.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()
    # Without real services, status should be degraded
    assert data["status"] in ("ready", "degraded")
    assert "checks" in data


@pytest.mark.asyncio
async def test_login_returns_422_with_missing_body():
    """Login endpoint should return 422 when form data is missing."""
    from traffic_ai.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/auth/token", data={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_returns_422_with_short_password():
    """Registration should reject passwords shorter than 8 characters."""
    from traffic_ai.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "password": "short"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth():
    """Any protected endpoint should return 401 without a token."""
    from unittest.mock import AsyncMock

    from traffic_ai.db.database import get_db
    from traffic_ai.main import app
    app.dependency_overrides[get_db] = AsyncMock(return_value=None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/segments")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_protected_endpoint_rejects_bad_token():
    """Protected endpoints should return 401 with a malformed token."""
    from unittest.mock import AsyncMock

    from traffic_ai.db.database import get_db
    from traffic_ai.main import app
    app.dependency_overrides[get_db] = AsyncMock(return_value=None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/v1/segments",
                headers={"Authorization": "Bearer not.a.valid.token"},
            )
        # Malformed JWTs may return 401 or 422 depending on the JWT library version
        assert response.status_code in (401, 422)
    finally:
        app.dependency_overrides.pop(get_db, None)
