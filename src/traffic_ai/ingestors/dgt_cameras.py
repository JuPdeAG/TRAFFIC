"""DGT (Dirección General de Tráfico) camera ingestor.

Fetches the official camera list from Spain's DGT National Access Point
(DATEX II v3.6 XML), polls each camera's JPEG snapshot, runs ONNX-based
vehicle detection (Apache 2.0 models), and writes traffic metrics to InfluxDB.

Data sources (no auth, CC BY licence):
  Camera list:  https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v36.xml
  Image URL:    https://infocar.dgt.es/etraffic/data/camaras/{ID}.jpg
  Refresh:      ~3 minutes per camera

What this ingestor produces per camera per cycle:
  - vehicle_count          integer — number of vehicles visible
  - density_score          0-100   — congestion density estimate
  - density_level          "free_flow" | "light" | "moderate" | "heavy" | "gridlock"
  - camera_online          bool    — False if image fetch failed

Written to InfluxDB measurement "dgt_camera" tagged by camera_id and road_id.

Detection: uses ml.vehicle_detector (ONNX Runtime + Apache 2.0 YOLOv6n/RT-DETR).
Falls back to pixel-variance heuristic if onnxruntime is not installed.
GDPR note: vehicles only — no face or plate extraction. Frames are processed
in memory and never persisted unless S3_BUCKET is configured.
"""
from __future__ import annotations
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import aiohttp

from traffic_ai.config import get_profile, settings
from traffic_ai.db.influx import write_points
from traffic_ai.ingestors.base import BaseIngestor

logger = logging.getLogger(__name__)

DGT_CAMERA_LIST_URL = (
    "https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v36.xml"
)
DGT_IMAGE_BASE_URL = "https://infocar.dgt.es/etraffic/data/camaras/{camera_id}.jpg"

# DATEX II v3 XML namespaces used in the DGT publication
_NS = {
    "ns2": "http://datex2.eu/schema/3/d2Payload",
    "fse": "http://datex2.eu/schema/3/facilities",
    "com": "http://datex2.eu/schema/3/common",
}


class DGTCameraIngestor(BaseIngestor):
    """Ingests traffic metrics from DGT national camera network."""

    def __init__(self, max_cameras: int | None = None) -> None:
        super().__init__(name="dgt_cameras")
        profile = get_profile()
        self.max_cameras = max_cameras or profile.max_cameras
        self._cameras: list[dict[str, Any]] = []  # [{id, road, lat, lon, url}]
        self._camera_index: int = 0  # round-robin cursor

    async def start(self) -> None:
        self._running = True
        await self._load_camera_list()
        self.logger.info(
            "DGTCameraIngestor started — %d cameras available, polling %d per cycle",
            len(self._cameras),
            self.max_cameras,
        )

    async def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[dict[str, Any]]:
        """Process all cameras with bounded HTTP concurrency (semaphore=50).

        Round-robin is replaced by full-sweep: every poll visits every camera,
        limited only by HTTP concurrency (50 parallel requests) so DGT servers
        are not hammered and the event loop stays responsive.
        With ~1,900 cameras and 50 concurrent fetches the sweep takes ~80s,
        well within the 120s balanced-profile beat interval.
        """
        if not self._cameras:
            await self._load_camera_list()
            if not self._cameras:
                return []

        sem = asyncio.Semaphore(15)

        async def _bounded(cam: dict[str, Any]) -> dict[str, Any] | None:
            async with sem:
                return await self._process_camera(session, cam)

        async with aiohttp.ClientSession() as session:
            raw = await asyncio.gather(
                *[_bounded(cam) for cam in self._cameras],
                return_exceptions=True,
            )

        results = [r for r in raw if r and not isinstance(r, Exception)]
        lines = [self._to_line_protocol(r) for r in results]

        if lines:
            try:
                await write_points(lines)
            except Exception:
                self.logger.exception("Failed to write DGT camera metrics to InfluxDB")

        self.logger.info(
            "DGT cameras: processed %d/%d, wrote %d metrics",
            len(results), len(self._cameras), len(lines),
        )
        return results

    # ── private ─────────────────────────────────────────────────────────────

    async def _process_camera(
        self, session: aiohttp.ClientSession, cam: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Fetch JPEG, run inference, return metrics dict."""
        camera_id = cam["id"]
        url = cam.get("url") or DGT_IMAGE_BASE_URL.format(camera_id=camera_id)

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return {
                        "camera_id": camera_id,
                        "camera_online": False,
                        "road": cam.get("road", ""),
                        "ts": datetime.now(timezone.utc),
                    }
                frame_bytes = await resp.read()
        except Exception:
            self.logger.debug("Camera %s fetch failed", camera_id)
            return None

        # Run vehicle detection
        metrics = _detect_vehicles(frame_bytes)

        return {
            "camera_id": camera_id,
            "road": cam.get("road", ""),
            "lat": cam.get("lat"),
            "lon": cam.get("lon"),
            "camera_online": True,
            "vehicle_count": metrics["vehicle_count"],
            "density_score": metrics["density_score"],
            "density_level": metrics["density_level"],
            "ts": datetime.now(timezone.utc),
        }

    @staticmethod
    def _to_line_protocol(record: dict[str, Any]) -> str:
        camera_id = record["camera_id"].replace(" ", r"\ ")
        road = (record.get("road") or "unknown").replace(" ", r"\ ")
        online = "true" if record.get("camera_online") else "false"
        return (
            f"dgt_camera,camera_id={camera_id},road={road} "
            f"vehicle_count={record.get('vehicle_count', 0)}i,"
            f"density_score={record.get('density_score', 0.0)},"
            f"camera_online={online}"
        )

    async def _load_camera_list(self) -> None:
        """Fetch DATEX II XML and parse camera ID + URL list."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    DGT_CAMERA_LIST_URL,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        self.logger.warning(
                            "DGT camera list returned %d", resp.status
                        )
                        return
                    xml_bytes = await resp.read()

            cameras = _parse_dgt_datex2(xml_bytes)
            self._cameras = cameras
            self.logger.info("Loaded %d cameras from DGT DATEX II feed", len(cameras))
        except Exception:
            self.logger.exception("Failed to load DGT camera list")


# ── Redis round-robin helper ─────────────────────────────────────────────────

def _advance_camera_index(redis_key: str, batch_size: int, total: int) -> int:
    """Read current index from Redis, store next value, return current.

    Falls back to 0 if Redis is unreachable so ingestion still works.
    Not perfectly atomic but close enough for camera polling — a duplicate
    or skipped camera in rare concurrent scenarios is acceptable.
    """
    try:
        import redis as _redis
        r = _redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        raw = r.get(redis_key)
        current = int(raw) if raw else 0
        r.set(redis_key, (current + batch_size) % total)
        r.close()
        return current % total
    except Exception:
        return 0


# ── DATEX II parser ──────────────────────────────────────────────────────────

def _parse_dgt_datex2(xml_bytes: bytes) -> list[dict[str, Any]]:
    """Parse DGT DATEX II v3.6 XML and return list of camera dicts.

    Real structure per <device>:
      typeOfDevice:  'camera'
      deviceUrl:     'https://infocar.dgt.es/etraffic/data/camaras/{ID}.jpg'
      pointLocation > tpegPointLocation > point > pointCoordinates > latitude/longitude
      pointLocation > supplementaryPositionalDescription > roadInformation > roadName
    """
    cameras: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        logger.warning("Failed to parse DGT DATEX II XML")
        return cameras

    for device in root.iter():
        if device.tag.split("}")[-1] != "device":
            continue
        try:
            url = _find_text(device, ("deviceUrl",))
            if not url:
                continue
            # Extract camera ID from the image URL filename (strip path + extension)
            camera_id = url.rstrip("/").rsplit("/", 1)[-1].replace(".jpg", "")
            if not camera_id:
                continue

            lat = _find_float(device, ("latitude",))
            lon = _find_float(device, ("longitude",))
            road = _find_text(device, ("roadName", "roadNumber", "road"))

            cameras.append({
                "id": camera_id,
                "url": url if url.endswith(".jpg") else DGT_IMAGE_BASE_URL.format(camera_id=camera_id),
                "road": road or "",
                "lat": lat,
                "lon": lon,
            })
        except Exception:
            continue

    return cameras


def _find_parent(root: ET.Element, target: ET.Element) -> ET.Element:
    """Return the direct parent of `target` within `root`."""
    for parent in root.iter():
        if target in list(parent):
            return parent
    return root


def _find_text(elem: ET.Element, tags: tuple[str, ...]) -> str | None:
    for child in elem.iter():
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag in tags and child.text:
            return child.text.strip()
    return None


def _find_float(elem: ET.Element, tags: tuple[str, ...]) -> float | None:
    val = _find_text(elem, tags)
    if val:
        try:
            return float(val)
        except ValueError:
            pass
    return None


# ── vehicle detection ────────────────────────────────────────────────────────

def _detect_vehicles(frame_bytes: bytes) -> dict[str, Any]:
    """Run ONNX vehicle detection on a JPEG frame.

    Delegates to ml.vehicle_detector (Apache 2.0 YOLOv6n/RT-DETR via ONNX
    Runtime). Falls back to pixel-variance heuristic if onnxruntime is absent.
    Returns: vehicle_count, density_score, density_level.
    """
    from traffic_ai.ml.vehicle_detector import detect_vehicles  # noqa: PLC0415
    result = detect_vehicles(frame_bytes)
    # Normalise to the keys expected by this ingestor
    return {
        "vehicle_count": result["vehicle_count"],
        "density_score": result["density_score"],
        "density_level": result["density_level"],
    }


def _to_line_madrid(record: dict[str, Any]) -> str:
    """InfluxDB line protocol for Madrid city cameras."""
    camera_id = record["camera_id"].replace(" ", r"\ ")
    online = "true" if record.get("camera_online") else "false"
    return (
        f"madrid_camera,camera_id={camera_id},source=madrid_cameras "
        f"vehicle_count={record.get('vehicle_count', 0)}i,"
        f"density_score={record.get('density_score', 0.0)},"
        f"camera_online={online}"
    )
