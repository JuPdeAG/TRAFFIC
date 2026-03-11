"""Celery tasks for camera frame processing."""
from __future__ import annotations
import logging
from traffic_ai.celery_app import app
from traffic_ai.config import get_profile

logger = logging.getLogger(__name__)


@app.task(name="traffic_ai.tasks.camera_tasks.process_frame", bind=True, max_retries=3, default_retry_delay=30)
def process_frame(self, camera_id: str, s3_key: str) -> dict:
    """Process a single camera frame for vehicle detection and damage analysis."""
    profile = get_profile()
    logger.info("Processing frame from camera %s: %s", camera_id, s3_key)
    try:
        result = {
            "camera_id": camera_id, "s3_key": s3_key,
            "vehicles_detected": 0, "damage_detected": False,
            "onnx_enabled": profile.enable_onnx,
        }
        return result
    except Exception as exc:
        logger.exception("Frame processing failed for %s", s3_key)
        raise self.retry(exc=exc)
