"""Health and readiness endpoints."""
from __future__ import annotations
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/v1/health")
async def health_check() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/api/v1/ready")
async def readiness_check() -> dict:
    """Readiness probe -- checks db, redis, influx."""
    checks: dict[str, str] = {}
    try:
        from traffic_ai.db.database import async_session_factory
        if async_session_factory is not None:
            async with async_session_factory() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        else:
            checks["postgres"] = "not initialised"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"
    try:
        from traffic_ai.db.redis_client import get_redis
        r = await get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
    try:
        from traffic_ai.db.influx import get_influx_client
        client = get_influx_client()
        ready = await client.ping()
        checks["influxdb"] = "ok" if ready else "not ready"
    except Exception as exc:
        checks["influxdb"] = f"error: {exc}"
    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}
