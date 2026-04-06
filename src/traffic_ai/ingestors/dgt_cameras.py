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


_STRATEGY_KEY = "camera:strategy"
_DEFAULT_STRATEGY: dict[str, Any] = {
    "mode": "all",         # "all" | "roads" | "bbox"
    "roads": [],           # list of road names for "roads" mode
    "bbox": {},            # {lat_min, lat_max, lon_min, lon_max} for "bbox" mode
    "batch_size": 100,     # 100 cameras/batch keeps peak worker RAM ~550MB
    "semaphore": 8,        # 8 concurrent ONNX inferences — RAM-safe on t4g.small
}


def _read_strategy() -> dict[str, Any]:
    """Read camera strategy from Redis. Falls back to defaults if unavailable."""
    try:
        import redis as _redis, json
        r = _redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        raw = r.get(_STRATEGY_KEY)
        r.close()
        if raw:
            stored = json.loads(raw)
            return {**_DEFAULT_STRATEGY, **stored}
    except Exception:
        pass
    return dict(_DEFAULT_STRATEGY)


class DGTCameraIngestor(BaseIngestor):
    """Ingests traffic metrics from DGT national camera network."""

    def __init__(self) -> None:
        super().__init__(name="dgt_cameras")
        self._cameras: list[dict[str, Any]] = []  # [{id, road, lat, lon, url}]
        self._camera_index: int = 0  # round-robin cursor

    async def start(self) -> None:
        self._running = True
        if not self._cameras:
            await self._load_camera_list()
        self.logger.info("DGTCameraIngestor started — %d cameras loaded", len(self._cameras))

    async def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[dict[str, Any]]:
        """Process one batch of cameras using strategy and params from Redis.

        Strategy (mode/roads/bbox) filters the active camera set.
        batch_size and semaphore are read from Redis so the admin panel
        can tune them without redeploying.
        """
        if not self._cameras:
            await self._load_camera_list()
            if not self._cameras:
                return []

        strategy = _read_strategy()
        batch_size = max(50, min(800, int(strategy.get("batch_size", 400))))
        semaphore  = max(5,  min(80,  int(strategy.get("semaphore",  30))))

        active = _apply_strategy(self._cameras, strategy)
        if not active:
            self.logger.warning("Camera strategy filtered to 0 cameras — falling back to all")
            active = self._cameras

        total = len(active)
        start = self._camera_index % total
        batch = active[start:start + batch_size]
        if len(batch) < batch_size:
            batch += active[:batch_size - len(batch)]
        self._camera_index = (start + batch_size) % total

        sem = asyncio.Semaphore(semaphore)

        async def _bounded(cam: dict[str, Any]) -> dict[str, Any] | None:
            async with sem:
                return await self._process_camera(session, cam)

        async with aiohttp.ClientSession() as session:
            raw = await asyncio.gather(
                *[_bounded(cam) for cam in batch],
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
        """Fetch DATEX II XML and parse camera ID + URL list.

        Cameras are sorted so major Spanish highways come first in every
        round-robin rotation, ensuring the most traffic-critical roads are
        always covered even if a sweep is interrupted.
        """
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
            self._cameras = _sort_by_priority(cameras)
            self.logger.info("Loaded %d cameras from DGT DATEX II feed", len(cameras))
        except Exception:
            self.logger.exception("Failed to load DGT camera list")


# ── Highway priority sort ────────────────────────────────────────────────────

_PRIORITY_ROADS = {
    # Tier 1 — Madrid ring roads and radials (highest traffic)
    "M-30", "M-40", "M-50", "M-45", "M-60",
    "A-1", "A-2", "A-3", "A-4", "A-5", "A-6",
    # Tier 2 — National highways
    "AP-7", "AP-6", "AP-36", "AP-41",
    "A-7", "A-8", "A-9", "A-92",
    "N-I", "N-II", "N-III", "N-IV", "N-V", "N-VI",
    # Tier 3 — Barcelona
    "B-10", "B-20", "B-23", "C-31", "C-32", "C-33", "C-58",
}


def _sort_by_priority(cameras: list[dict]) -> list[dict]:
    """Return cameras sorted: major highways first, then all others."""
    def _priority(cam: dict) -> int:
        road = (cam.get("road") or "").upper()
        for r in _PRIORITY_ROADS:
            if r in road:
                return 0
        return 1
    return sorted(cameras, key=_priority)


def _apply_strategy(cameras: list[dict], strategy: dict[str, Any]) -> list[dict]:
    """Filter camera list according to strategy mode."""
    mode = strategy.get("mode", "all")
    if mode == "roads":
        roads = {r.upper().strip() for r in strategy.get("roads", []) if r}
        if not roads:
            return cameras
        return [c for c in cameras if any(r in (c.get("road") or "").upper() for r in roads)]
    if mode == "bbox":
        bbox = strategy.get("bbox", {})
        try:
            lat_min = float(bbox["lat_min"])
            lat_max = float(bbox["lat_max"])
            lon_min = float(bbox["lon_min"])
            lon_max = float(bbox["lon_max"])
        except (KeyError, TypeError, ValueError):
            return cameras
        return [
            c for c in cameras
            if c.get("lat") and c.get("lon")
            and lat_min <= float(c["lat"]) <= lat_max
            and lon_min <= float(c["lon"]) <= lon_max
        ]
    return cameras  # "all"


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
