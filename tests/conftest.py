"""Shared pytest fixtures for Traffic AI tests.

Note: DB-dependent tests require PostgreSQL with PostGIS due to GeoAlchemy2
geometry columns. SQLite in-memory is NOT compatible with PostGIS types.

For unit tests (config, throttle), use mocks instead of real DB sessions.
For integration tests, use testcontainers-postgres or a real PostGIS instance.

Dev dependency: aiosqlite (for any future SQLite-compatible test paths)
"""
from __future__ import annotations
import asyncio
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Mark: DB-dependent fixtures require PostgreSQL + PostGIS
# The ORM models use GeoAlchemy2 Geometry columns which are incompatible with SQLite.
requires_postgres = pytest.mark.skipif(
    True,  # Set to False when a PostgreSQL test instance is available
    reason="Requires PostgreSQL with PostGIS extension (GeoAlchemy2 columns)",
)


@pytest_asyncio.fixture
async def db_session():
    """Provide a test database session using PostgreSQL.

    Requires a running PostGIS instance. Set TEST_DATABASE_URL env var.
    Skipped automatically when the database is unavailable.
    """
    import os
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from traffic_ai.models.orm import Base

    test_db_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://traffic:traffic@localhost:5432/traffic_ai_test",
    )
    try:
        engine = create_async_engine(test_db_url, connect_args={})
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        pytest.skip("PostgreSQL/PostGIS not available")
        return
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client for the FastAPI app."""
    from traffic_ai.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
