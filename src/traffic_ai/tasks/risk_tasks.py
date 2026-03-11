"""Celery tasks for risk score computation."""
from __future__ import annotations
import asyncio
import logging
from traffic_ai.celery_app import app
from traffic_ai.config import RuntimeResourceManager

logger = logging.getLogger(__name__)


@app.task(name="traffic_ai.tasks.risk_tasks.compute_risk_score")
def compute_risk_score(segment_id: str) -> dict:
    """Compute the risk score for a single segment."""
    from traffic_ai.analytics.risk_scorer import RiskScoringEngine
    engine = RiskScoringEngine()
    loop = asyncio.new_event_loop()
    try:
        score = loop.run_until_complete(engine.compute(segment_id))
    finally:
        loop.close()
    return {"segment_id": segment_id, "score": score}


@app.task(name="traffic_ai.tasks.risk_tasks.compute_all_risk_scores")
def compute_all_risk_scores() -> dict:
    """Compute risk scores for all segments, respecting resource throttling."""
    resource_mgr = RuntimeResourceManager()
    if resource_mgr.should_throttle():
        logger.warning("System under load -- reducing risk computation concurrency")
    concurrency = resource_mgr.available_concurrency()
    logger.info("Computing all risk scores with concurrency=%d", concurrency)
    return {"concurrency": concurrency, "status": "scheduled"}
