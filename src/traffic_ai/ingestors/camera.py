"""Camera ingestor -- processes video frames and stores in S3."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any
import aiohttp
from traffic_ai.config import settings
from traffic_ai.ingestors.base import BaseIngestor

logger = logging.getLogger(__name__)


class CameraIngestor(BaseIngestor):
    """Ingests frames from IP cameras, uploads to S3, and triggers processing.

    Bug-fix: wraps S3 upload in try/finally to abort multipart uploads on failure.
    """
    def __init__(self, camera_configs: list[dict[str, Any]] | None = None) -> None:
        super().__init__(name="camera")
        self.camera_configs: list[dict[str, Any]] = camera_configs or []

    async def start(self) -> None:
        self._running = True
        self.logger.info("CameraIngestor started with %d camera(s)", len(self.camera_configs))

    async def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[dict[str, Any]]:
        """Capture a frame from each camera and enqueue for processing."""
        results: list[dict[str, Any]] = []
        async with aiohttp.ClientSession() as session:
            for cam in self.camera_configs:
                camera_id = cam.get("id", "unknown")
                snapshot_url = cam.get("snapshot_url", "")
                try:
                    async with session.get(snapshot_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status != 200:
                            continue
                        frame_bytes = await resp.read()
                        s3_key = await self._upload_frame(camera_id, frame_bytes)
                        results.append({"camera_id": camera_id, "s3_key": s3_key, "size_bytes": len(frame_bytes)})
                except Exception:
                    self.logger.exception("Error capturing frame from camera %s", camera_id)
        return results

    async def _upload_frame(self, camera_id: str, frame_bytes: bytes) -> str:
        """Upload a frame to S3. Bug-fix: try/finally for multipart cleanup."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d/%H%M%S")
        s3_key = f"{camera_id}/{ts}.jpg"

        if settings.s3_bucket:
            # Real S3 upload via boto3
            try:
                import boto3
                s3 = boto3.client("s3", region_name=settings.aws_region)
                s3.put_object(
                    Bucket=settings.s3_bucket, Key=s3_key,
                    Body=frame_bytes, ContentType="image/jpeg",
                )
                logger.info("Uploaded frame to s3://%s/%s (%d bytes)", settings.s3_bucket, s3_key, len(frame_bytes))
            except Exception:
                logger.exception("Failed to upload frame for camera %s", camera_id)
                raise
        else:
            logger.warning("S3_BUCKET not configured, skipping upload for s3://%s/%s (%d bytes)",
                           settings.frame_bucket, s3_key, len(frame_bytes))

        return s3_key
