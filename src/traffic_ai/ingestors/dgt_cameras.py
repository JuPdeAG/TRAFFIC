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
        """Process the next batch of cameras in round-robin order."""
        if not self._cameras:
            await self._load_camera_list()
            if not self._cameras:
                return []

        # Round-robin: take the next max_cameras cameras from the list
        total = len(self._cameras)
        batch_size = min(self.max_cameras, total)
        indices = [(self._camera_index + i) % total for i in range(batch_size)]
        self._camera_index = (self._camera_index + batch_size) % total
        batch = [self._cameras[i] for i in indices]

        results: list[dict[str, Any]] = []
        lines: list[str] = []

        async with aiohttp.ClientSession() as session:
            for cam in batch:
                result = await self._process_camera(session, cam)
                if result:
                    results.append(result)
                    lines.append(self._to_line_protocol(result))

        if lines:
            try:
                await write_points(lines)
            except Exception:
                self.logger.exception("Failed to write DGT camera metrics to InfluxDB")

        self.logger.info(
            "DGT cameras: processed %d/%d, wrote %d metrics",
            len(results), len(batch), len(lines),
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


# ── DATEX II parser ──────────────────────────────────────────────────────────

def _parse_dgt_datex2(xml_bytes: bytes) -> list[dict[str, Any]]:
    """Parse DGT DATEX II v3.6 XML and return list of camera dicts."""
    cameras: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        logger.warning("Failed to parse DGT DATEX II XML")
        return cameras

    # Walk all elements looking for camera IDs and image URLs.
    # The structure varies slightly between DGT DATEX II versions so we
    # search by tag suffix rather than full namespace path.
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag in ("cameraId", "deviceIdentifier"):
            camera_id = (elem.text or "").strip()
            if not camera_id:
                continue
            # Find sibling URL element
            parent = _find_parent(root, elem)
            url = _find_text(parent, ("deviceUrl", "cameraImageUrl", "imageUrl"))
            lat = _find_float(parent, ("latitude",))
            lon = _find_float(parent, ("longitude",))
            road = _find_text(parent, ("roadNumber", "road"))
            cameras.append({
                "id": camera_id,
                "url": url or DGT_IMAGE_BASE_URL.format(camera_id=camera_id),
                "road": road or "",
                "lat": lat,
                "lon": lon,
            })
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
