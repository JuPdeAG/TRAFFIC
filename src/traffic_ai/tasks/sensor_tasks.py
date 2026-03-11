"""Celery tasks for sensor data ingestion."""
from __future__ import annotations
import asyncio
import logging
from traffic_ai.celery_app import app
from traffic_ai.config import get_profile, settings

logger = logging.getLogger(__name__)


@app.task(name="traffic_ai.tasks.sensor_tasks.poll_loop_detectors")
def poll_loop_detectors() -> dict:
    """Poll all configured loop detectors for new readings."""
    from traffic_ai.ingestors.loop_detector import LoopDetectorIngestor
    profile = get_profile()
    detector_urls = settings.loop_detector_url_list
    logger.info("Polling loop detectors (max=%d, configured=%d)", profile.max_loop_detectors, len(detector_urls))
    ingestor = LoopDetectorIngestor(detector_urls=detector_urls[:profile.max_loop_detectors])
    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(ingestor.poll())
    finally:
        loop.close()
    return {"polled": len(results)}


@app.task(name="traffic_ai.tasks.sensor_tasks.recalculate_baselines")
def recalculate_baselines() -> dict:
    """Recalculate speed baselines for all segments."""
    from traffic_ai.analytics.baseline import BaselineCalculator
    from traffic_ai.db.database import sync_session_context
    logger.info("Recalculating speed baselines")
    loop = asyncio.new_event_loop()
    try:
        async def _run():
            from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
            engine = create_async_engine(settings.database_url)
            session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with session_factory() as session:
                calculator = BaselineCalculator(db=session)
                count = await calculator.recalculate_all()
                await session.commit()
            await engine.dispose()
            return count
        count = loop.run_until_complete(_run())
    finally:
        loop.close()
    return {"segments_updated": count}
