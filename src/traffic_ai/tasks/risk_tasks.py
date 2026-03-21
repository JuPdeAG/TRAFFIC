"""Celery tasks for risk score computation and alert generation."""
from __future__ import annotations
import asyncio
import logging
from traffic_ai.celery_app import app
from traffic_ai.config import RuntimeResourceManager

logger = logging.getLogger(__name__)


@app.task(name="traffic_ai.tasks.risk_tasks.compute_risk_score", bind=True, max_retries=2)
def compute_risk_score(self, segment_id: str, pilot: str = "default") -> dict:
    """Compute the risk score for a single segment and evaluate alert thresholds."""
    from traffic_ai.analytics.alert_engine import evaluate_and_alert
    from traffic_ai.db.database import init_db, async_session_factory

    async def _run() -> dict:
        await init_db()
        assert async_session_factory is not None
        async with async_session_factory() as session:
            from traffic_ai.analytics.risk_scorer_ml import MLRiskScoringEngine  # noqa: PLC0415
            engine = MLRiskScoringEngine(db=session)
            result = await engine.compute_with_explanation(segment_id)
            score = result["score"]
            actions = await evaluate_and_alert(session, segment_id, score, pilot=pilot)
            await session.commit()

        # Persist score to InfluxDB for trend charts
        await _write_risk_score(segment_id, score, result.get("level", "low"))
        return {**result, "alert_actions": actions}

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    except Exception as exc:
        logger.exception("Risk computation failed for segment %s", segment_id)
        raise self.retry(exc=exc, countdown=30)
    finally:
        loop.close()


@app.task(name="traffic_ai.tasks.risk_tasks.compute_all_risk_scores")
def compute_all_risk_scores() -> dict:
    """Compute risk scores for all segments, respecting resource throttling."""
    from traffic_ai.db.database import init_db, async_session_factory
    from sqlalchemy import select
    from traffic_ai.models.orm import RoadSegment

    resource_mgr = RuntimeResourceManager()
    if resource_mgr.should_throttle():
        logger.warning("System under load — reducing risk computation concurrency")
    concurrency = resource_mgr.available_concurrency()

    async def _get_segments() -> list[tuple[str, str]]:
        await init_db()
        assert async_session_factory is not None
        async with async_session_factory() as session:
            result = await session.execute(select(RoadSegment.id, RoadSegment.pilot))
            return [(row[0], row[1]) for row in result.all()]

    loop = asyncio.new_event_loop()
    try:
        segments = loop.run_until_complete(_get_segments())
    finally:
        loop.close()

    dispatched = 0
    for segment_id, pilot in segments:
        compute_risk_score.apply_async(
            args=[segment_id, pilot],
            queue="default",
        )
        dispatched += 1

    logger.info("Dispatched risk computation for %d segments (concurrency=%d)", dispatched, concurrency)
    return {"dispatched": dispatched, "concurrency": concurrency}


async def _write_risk_score(segment_id: str, score: float, level: str) -> None:
    """Persist a risk score point to InfluxDB for historical trend charts."""
    try:
        from traffic_ai.db.influx import write_points  # noqa: PLC0415
        seg = segment_id.replace(" ", r"\ ").replace(",", r"\,")
        lvl = level.replace(" ", r"\ ")
        line = f"risk_score,segment_id={seg},level={lvl} score={score}"
        await write_points([line])
    except Exception:
        logger.debug("Failed to write risk score to InfluxDB for %s", segment_id)
