"""SQLAlchemy async database engine and session management."""
from __future__ import annotations
import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)
from traffic_ai.config import settings

logger = logging.getLogger(__name__)
engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """Create the async engine and session factory."""
    global engine, async_session_factory
    engine = create_async_engine(
        settings.database_url, echo=(settings.environment == "development"),
        pool_size=10, max_overflow=20,
    )
    async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    logger.info("Database engine initialised: %s", settings.database_url)


async def close_db() -> None:
    """Dispose of the engine connection pool."""
    global engine
    if engine is not None:
        await engine.dispose()
        logger.info("Database engine disposed.")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    assert async_session_factory is not None, "Database not initialised"
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
