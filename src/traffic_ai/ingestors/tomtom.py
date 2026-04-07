"""TomTom Traffic API ingestors.

Two ingestors:
  TomTomIncidentsIngestor — national Spain incidents (1 API call per poll)
  TomTomFlowIngestor      — flow data for key highway coordinate points

Free tier budget: 2,500 requests/day.
  Incidents every 5 min  → 288 calls/day
  Flow (6 pts) every 10 min → 6 × 144 = 864 calls/day
  Total: ~1,152 calls/day  (46% of free tier)

Incident magnitude: 1=minor, 2=moderate, 3=major, 4=undefined/road_closed
Incident types (subset): 1=accident, 6=jam, 7=lane_closed, 8=road_closed,
    9=road_works, 14=broken_down_vehicle

Spain bounding box: minLon=-9.3, minLat=36.0, maxLon=3.3, maxLat=43.8

Docs: https://developer.tomtom.com/traffic-api/documentation/traffic-flow/flow-segment-data
      https://developer.tomtom.com/traffic-api/documentation/traffic-incidents/incident-details
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from traffic_ai.config import settings
from traffic_ai.db.influx import write_points
from traffic_ai.ingestors.base import BaseIngestor

logger = logging.getLogger(__name__)

# Spain bounding box (minLon, minLat, maxLon, maxLat)
# TomTom incidents API max bbox is 10,000 km² — Spain (~505,000 km²) doesn't fit.
# Use per-city bboxes instead (each well under the limit).
_CITY_BBOXES: list[tuple[str, str]] = [
    ("-4.0,40.2,-3.3,40.7", "madrid"),    # ~3,000 km²
    ("-0.6,39.3,0.0,39.7",  "valencia"),  # ~2,500 km²
    ("1.8,41.2,2.5,41.6",   "barcelona"), # ~2,700 km²
]

# Approximate city centres used as fallback when geometry is absent
_CITY_CENTRES: dict[str, tuple[float, float]] = {
    "madrid":    (40.4168, -3.7038),
    "valencia":  (39.4699, -0.3763),
    "barcelona": (41.3851,  2.1734),
}

# Key highway coordinates: (name, lat, lon)
# These cover the major arterials in Madrid, Barcelona, Valencia
DEFAULT_FLOW_POINTS: list[tuple[str, float, float]] = [
    ("madrid_m30",    40.4168, -3.7038),
    ("madrid_a6",     40.5236, -3.8236),
    ("madrid_a1",     40.6266, -3.7234),
    ("madrid_a2",     40.4500, -3.5500),
    ("barcelona_ap7", 41.3851,  2.1734),
    ("valencia_a3",   39.4699, -0.3763),
]

_INCIDENT_TYPE_NAMES: dict[int, str] = {
    0: "unknown", 1: "accident", 2: "fog", 3: "dangerous_conditions",
    4: "rain", 5: "ice", 6: "jam", 7: "lane_closed", 8: "road_closed",
    9: "road_works", 10: "wind", 11: "flooding", 14: "broken_down_vehicle",
}

_MAGNITUDE_NAMES: dict[int, str] = {
    0: "unknown", 1: "minor", 2: "moderate", 3: "major", 4: "road_closed",
}

_BASE = "https://api.tomtom.com/traffic/services"


class TomTomIncidentsIngestor(BaseIngestor):
    """Polls TomTom for national Spain traffic incidents."""

    def __init__(self, api_key: str | None = None) -> None:
        super().__init__(name="tomtom_incidents")
        self._key = api_key or settings.tomtom_api_key

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[dict[str, Any]]:
        if not self._key:
            self.logger.warning("TOMTOM_API_KEY not set — skipping incidents poll")
            return []

        all_records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        try:
            async with aiohttp.ClientSession() as session:
                for bbox, city in _CITY_BBOXES:
                    # fields includes geometry{type,coordinates} for real GPS coords
                    # and the key properties we need for enrichment
                    url = (
                        f"{_BASE}/5/incidentDetails"
                        f"?bbox={bbox}"
                        "&language=es-ES"
                        "&timeValidityFilter=present"
                        f"&key={self._key}"
                    )
                    try:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                            if resp.status == 401:
                                self.logger.error("TomTom: invalid API key (401)")
                                return []
                            if resp.status == 429:
                                self.logger.warning("TomTom: rate limit hit (429)")
                                break
                            if resp.status != 200:
                                self.logger.warning("TomTom incidents bbox %s returned HTTP %d", bbox, resp.status)
                                continue
                            data = await resp.json(content_type=None)
                    except Exception:
                        self.logger.exception("Failed to fetch TomTom incidents for bbox %s", bbox)
                        continue

                    for r in _parse_incidents(data, city):
                        if r["id"] not in seen_ids:
                            seen_ids.add(r["id"])
                            all_records.append(r)
        except Exception:
            self.logger.exception("Failed to fetch TomTom incidents")
            return []

        if not all_records:
            return []

        lines = [_incident_to_line(r) for r in all_records]
        try:
            await write_points(lines)
            self.logger.info("TomTom incidents: wrote %d points", len(lines))
        except Exception:
            self.logger.exception("Failed to write TomTom incidents to InfluxDB")

        return all_records


class TomTomFlowIngestor(BaseIngestor):
    """Polls TomTom Flow Segment Data for key highway coordinate points."""

    def __init__(
        self,
        api_key: str | None = None,
        points: list[tuple[str, float, float]] | None = None,
    ) -> None:
        super().__init__(name="tomtom_flow")
        self._key = api_key or settings.tomtom_api_key
        self._points = points or DEFAULT_FLOW_POINTS

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[dict[str, Any]]:
        if not self._key:
            self.logger.warning("TOMTOM_API_KEY not set — skipping flow poll")
            return []

        records: list[dict[str, Any]] = []
        async with aiohttp.ClientSession() as session:
            for name, lat, lon in self._points:
                try:
                    record = await _fetch_flow_point(session, self._key, name, lat, lon)
                    if record:
                        records.append(record)
                except Exception:
                    self.logger.debug("TomTom flow failed for %s", name)

        if not records:
            return []

        lines = [_flow_to_line(r) for r in records]
        try:
            await write_points(lines)
            self.logger.info("TomTom flow: wrote %d points", len(lines))
        except Exception:
            self.logger.exception("Failed to write TomTom flow data to InfluxDB")

        return records


async def _fetch_flow_point(
    session: aiohttp.ClientSession,
    key: str,
    name: str,
    lat: float,
    lon: float,
) -> dict[str, Any] | None:
    url = (
        f"{_BASE}/4/flowSegmentData/absolute/10/json"
        f"?point={lat},{lon}&unit=KMPH&key={key}"
    )
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        if resp.status != 200:
            return None
        data = await resp.json(content_type=None)

    fd = data.get("flowSegmentData", {})
    current_speed = fd.get("currentSpeed", 0.0)
    free_flow_speed = fd.get("freeFlowSpeed", 0.0)
    confidence = fd.get("confidence", 0.0)
    road_closure = bool(fd.get("roadClosure", False))

    # Derive a density score: 0 = free_flow, 100 = standstill
    if road_closure:
        density_score = 100.0
    elif free_flow_speed and free_flow_speed > 0:
        density_score = max(0.0, min(100.0, (1 - current_speed / free_flow_speed) * 100))
    else:
        density_score = 0.0

    return {
        "point_id": name,
        "lat": lat,
        "lon": lon,
        "current_speed": float(current_speed),
        "free_flow_speed": float(free_flow_speed),
        "confidence": float(confidence),
        "road_closure": road_closure,
        "density_score": density_score,
        "source": "tomtom_flow",
        "ts": datetime.now(timezone.utc),
    }


def _parse_incidents(data: dict[str, Any], city: str = "") -> list[dict[str, Any]]:
    """Parse TomTom v5 incidentDetails response.

    The API returns incidents as GeoJSON features; properties include:
      id, iconCategory, magnitudeOfDelay, from, to, length, delay, roadNumbers
    Geometry (LineString or Point) is extracted for map positioning.
    """
    records: list[dict[str, Any]] = []
    ts = datetime.now(timezone.utc)
    fallback_lat, fallback_lon = _CITY_CENTRES.get(city, (40.4168, -3.7038))

    incidents = data.get("incidents") or data.get("features", [])
    for inc in incidents:
        try:
            props = inc.get("properties") or inc
            # v5: id is at Feature top level; v4 fallback: id is in properties
            inc_id = str(inc.get("id") or props.get("id") or "").strip()
            if not inc_id:
                continue

            # v5 API uses iconCategory (int) instead of type
            inc_type = int(props.get("iconCategory") or props.get("type") or 0)
            # v5 API uses magnitudeOfDelay instead of magnitude
            magnitude = int(props.get("magnitudeOfDelay") or props.get("magnitude") or 0)
            delay = float(props.get("delay") or 0)
            length = float(props.get("length") or 0)
            road_numbers = props.get("roadNumbers") or []
            road = road_numbers[0] if road_numbers else ""

            # Extract coordinates from GeoJSON geometry
            lat, lon = fallback_lat, fallback_lon
            geom = inc.get("geometry", {})
            coords = geom.get("coordinates")
            if coords:
                # LineString → first point; Point → coords directly
                first = coords[0] if isinstance(coords[0], list) else coords
                if len(first) >= 2:
                    lon, lat = float(first[0]), float(first[1])

            records.append({
                "id": inc_id,
                "type": inc_type,
                "type_name": _INCIDENT_TYPE_NAMES.get(inc_type, "unknown"),
                "magnitude": magnitude,
                "magnitude_name": _MAGNITUDE_NAMES.get(magnitude, "unknown"),
                "delay_s": delay,
                "length_m": length,
                "road": road,
                "city": city,
                "lat": lat,
                "lon": lon,
                "source": "tomtom",
                "ts": ts,
            })
        except Exception:
            logger.debug("Skipping malformed TomTom incident")

    return records


def _incident_to_line(r: dict[str, Any]) -> str:
    inc_id = r["id"].replace(" ", r"\ ").replace(",", r"\,")
    type_name = r["type_name"].replace(" ", r"\ ")
    road = (r["road"] or "unknown").replace(" ", r"\ ").replace(",", r"\,")
    city = (r.get("city") or "unknown").replace(" ", r"\ ")
    return (
        f"tomtom_incidents,id={inc_id},type={type_name},"
        f"magnitude={r['magnitude_name']},road={road},city={city},source=tomtom "
        f"delay_s={r['delay_s']},length_m={r['length_m']},"
        f"magnitude_i={r['magnitude']}i,type_i={r['type']}i,"
        f"lat={r['lat']},lon={r['lon']}"
    )


def _flow_to_line(r: dict[str, Any]) -> str:
    point_id = r["point_id"].replace(" ", r"\ ").replace(",", r"\,")
    return (
        f"tomtom_flow,point_id={point_id},source=tomtom "
        f"current_speed={r['current_speed']},"
        f"free_flow_speed={r['free_flow_speed']},"
        f"density_score={r['density_score']},"
        f"confidence={r['confidence']},"
        f"road_closure={'true' if r['road_closure'] else 'false'}"
    )
