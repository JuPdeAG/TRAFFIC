"""Madrid real-time traffic state ingestor.

Fetches the Informo Madrid per-tramo state XML — updated every 5 minutes by
the Ayuntamiento de Madrid traffic management centre.

This is different from the loop detector CSV ingestor (which gives raw vehicle
counts from individual sensors). This feed gives the *processed* state per road
section: speed, load, and a discrete congestion level.

Source:  https://informo.madrid.es/informo/tmadrid/pm.xml
License: Open data — Ayuntamiento de Madrid (CC BY 4.0)
Auth:    None

Fields per tramo (road section):
  id          — section identifier
  cod_via     — road code
  tipo_elem   — element type (M30, URB, etc.)
  descripcion — human-readable location
  velocidad   — average speed km/h (0 = no data)
  carga       — load percentage 0-100
  ocupacion   — occupancy percentage 0-100
  estado      — 0=no data, 1=fluid, 2=dense, 3=slow, 4=very slow,
                5=jam/retention, 6=closed
  st_x, st_y  — UTM coordinates (EPSG:23030)
"""
from __future__ import annotations
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import aiohttp

from traffic_ai.db.influx import write_points
from traffic_ai.ingestors.base import BaseIngestor

logger = logging.getLogger(__name__)

MADRID_STATE_URL = "https://informo.madrid.es/informo/tmadrid/pm.xml"

_ESTADO_TO_SCORE: dict[int, float] = {
    0: 0.0,   # no data
    1: 10.0,  # fluid
    2: 35.0,  # dense
    3: 55.0,  # slow
    4: 70.0,  # very slow
    5: 85.0,  # jam
    6: 100.0, # closed
}

_ESTADO_TO_LEVEL: dict[int, str] = {
    0: "unknown",
    1: "free_flow",
    2: "light",
    3: "moderate",
    4: "heavy",
    5: "congested",
    6: "closed",
}


class MadridTrafficStateIngestor(BaseIngestor):
    """Fetches Madrid per-tramo real-time traffic state from Informo XML."""

    def __init__(self) -> None:
        super().__init__(name="madrid_traffic_state")

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[dict[str, Any]]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    MADRID_STATE_URL,
                    timeout=aiohttp.ClientTimeout(total=20),
                    headers={"Accept-Encoding": "gzip"},
                ) as resp:
                    if resp.status != 200:
                        self.logger.warning("Informo Madrid returned HTTP %d", resp.status)
                        return []
                    xml_bytes = await resp.read()
        except Exception:
            self.logger.exception("Failed to fetch Madrid traffic state XML")
            return []

        records = _parse_madrid_state_xml(xml_bytes)
        if not records:
            return []

        lines = [_to_line_protocol(r) for r in records]
        try:
            await write_points(lines)
            self.logger.info("Madrid traffic state: wrote %d tramo points", len(lines))
        except Exception:
            self.logger.exception("Failed to write Madrid traffic state to InfluxDB")

        return records


def _child_text(pm: ET.Element, tag: str, default: str = "") -> str:
    el = pm.find(tag)
    return (el.text or default).strip() if el is not None else default


def _parse_madrid_state_xml(xml_bytes: bytes) -> list[dict[str, Any]]:
    """Parse the Informo Madrid pm.xml feed.

    The real feed uses child elements (not attributes) and the root tag is <pms>.
    Key child elements per <pm>:
      idelem       — sensor loop ID
      intensidad   — vehicles/hour
      ocupacion    — occupancy %
      carga        — load % (0-100)
      nivelServicio — congestion level (same scale as Madrid estado)
      error        — 'S' = sensor error / no data, 'N' = ok
    """
    records: list[dict[str, Any]] = []
    ts = datetime.now(timezone.utc)
    try:
        xml_str = xml_bytes.decode("utf-8-sig") if isinstance(xml_bytes, bytes) else xml_bytes
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        logger.warning("Failed to parse Madrid traffic state XML")
        return records

    for pm in root.iter("pm"):
        try:
            # Child-element format (real Informo feed)
            tramo_id = _child_text(pm, "idelem")
            if not tramo_id:
                continue

            # Skip sensors reporting an error
            if _child_text(pm, "error", "N") == "S":
                continue

            estado = int(_child_text(pm, "nivelServicio") or "0")
            load_pct = float(_child_text(pm, "carga") or "0")
            occupancy_pct = float(_child_text(pm, "ocupacion") or "0")
            # No direct speed in this feed; derive from nivelServicio
            speed_kmh = float(_child_text(pm, "velocidad") or "0")

            records.append({
                "tramo_id": f"mad_{tramo_id}",
                "description": _child_text(pm, "descripcion"),
                "speed_kmh": speed_kmh,
                "load_pct": load_pct,
                "occupancy_pct": occupancy_pct,
                "estado": estado,
                "density_score": _ESTADO_TO_SCORE.get(estado, 0.0),
                "density_level": _ESTADO_TO_LEVEL.get(estado, "unknown"),
                "source": "madrid_informo",
                "ts": ts,
            })
        except Exception:
            logger.debug("Skipping malformed Madrid pm element")

    return records


def _to_line_protocol(record: dict[str, Any]) -> str:
    tramo_id = record["tramo_id"].replace(" ", r"\ ").replace(",", r"\,")
    return (
        f"madrid_traffic,tramo_id={tramo_id},source=informo "
        f"speed_kmh={record['speed_kmh']},"
        f"load_pct={record['load_pct']},"
        f"occupancy_pct={record['occupancy_pct']},"
        f"density_score={record['density_score']},"
        f"estado={record['estado']}i"
    )
