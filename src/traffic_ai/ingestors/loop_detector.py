"""Loop-detector ingestor -- polls detector endpoints for speed/flow data."""
from __future__ import annotations
import logging
from typing import Any
import aiohttp
from traffic_ai.db.influx import write_points
from traffic_ai.ingestors.base import BaseIngestor

logger = logging.getLogger(__name__)


class LoopDetectorIngestor(BaseIngestor):
    """Ingests speed and flow data from inductive loop detectors."""
    def __init__(self, detector_urls: list[str] | None = None) -> None:
        super().__init__(name="loop_detector")
        self.detector_urls: list[str] = detector_urls or []

    async def start(self) -> None:
        self._running = True
        self.logger.info("LoopDetectorIngestor started with %d detector(s)", len(self.detector_urls))

    async def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[dict[str, Any]]:
        """Poll all configured detector endpoints and write to InfluxDB."""
        results: list[dict[str, Any]] = []
        async with aiohttp.ClientSession() as session:
            for url in self.detector_urls:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            self.logger.warning("Detector %s returned status %d", url, resp.status)
                            continue
                        data = await resp.json()
                        results.append(data)
                        segment_id = data.get("segment_id", "unknown")
                        speed = data.get("speed_kmh", 0)
                        flow = data.get("flow_veh_h", 0)
                        occupancy = data.get("occupancy_pct", 0)
                        line = (
                            f"loop_detector,segment_id={segment_id} "
                            f"speed_kmh={speed},flow_veh_h={flow},occupancy_pct={occupancy}"
                        )
                        await write_points(line)
                except Exception:
                    self.logger.exception("Error polling detector %s", url)
        return results
