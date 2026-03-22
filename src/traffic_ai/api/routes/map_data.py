"""Map data endpoint — returns GeoJSON for live overlay layers.

GET /api/v1/map-data

Returns a single JSON object with three GeoJSON FeatureCollections:
  flow       — TomTom flow segment readings for 6 key Spanish highways
  incidents  — active incidents stored in PostgreSQL
  cameras    — DGT cameras (latest InfluxDB snapshot, where lat/lon is known)
"""
from __future__ import annotations
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from traffic_ai.api.deps import get_current_user
from traffic_ai.db.database import get_db
from traffic_ai.db.influx import query_points
from traffic_ai.models.orm import Incident, User

logger = logging.getLogger(__name__)
router = APIRouter()

# Mirrors DEFAULT_FLOW_POINTS in ingestors/tomtom.py
_FLOW_COORDS: dict[str, tuple[float, float, str]] = {
    "madrid_m30":    (40.4168, -3.7038, "Madrid M-30"),
    "madrid_a6":     (40.5236, -3.8236, "Madrid A-6 NW"),
    "madrid_a1":     (40.6266, -3.7234, "Madrid A-1 N"),
    "madrid_a2":     (40.4500, -3.5500, "Madrid A-2 E"),
    "barcelona_ap7": (41.3851,  2.1734, "Barcelona AP-7"),
    "valencia_a3":   (39.4699, -0.3763, "Valencia A-3"),
}


@router.get("/map-data")
async def get_map_data(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return live GeoJSON layers for the traffic map."""
    flow, incidents = await _gather(db)
    return {
        "flow": flow,
        "incidents": incidents,
    }


async def _gather(db: AsyncSession) -> tuple[dict, dict]:
    import asyncio
    flow_task = asyncio.create_task(_get_flow_geojson())
    inc_task = asyncio.create_task(_get_incidents_geojson(db))
    flow = await flow_task
    incidents = await inc_task
    return flow, incidents


async def _get_flow_geojson() -> dict[str, Any]:
    """Query InfluxDB for latest TomTom flow readings; join with known coords."""
    flux = """
    from(bucket: "traffic_metrics")
      |> range(start: -20m)
      |> filter(fn: (r) => r._measurement == "tomtom_flow")
      |> last()
    """
    try:
        rows = await query_points(flux)
    except Exception:
        logger.exception("Failed to query tomtom_flow from InfluxDB")
        rows = []

    # Group rows by point_id → latest values
    by_point: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid = row.get("point_id", "")
        if pid not in by_point:
            by_point[pid] = {}
        field = row.get("_field", "")
        val = row.get("_value")
        if field and val is not None:
            by_point[pid][field] = val

    features: list[dict] = []
    for point_id, (lat, lon, label) in _FLOW_COORDS.items():
        vals = by_point.get(point_id, {})
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "point_id": point_id,
                "label": label,
                "density_score": round(float(vals.get("density_score", -1)), 1),
                "current_speed": round(float(vals.get("current_speed", -1)), 1),
                "free_flow_speed": round(float(vals.get("free_flow_speed", -1)), 1),
                "road_closure": bool(vals.get("road_closure", False)),
                "has_data": bool(vals),
            },
        })

    return {"type": "FeatureCollection", "features": features}


async def _get_incidents_geojson(db: AsyncSession) -> dict[str, Any]:
    """Return active Postgres incidents that have a location geometry."""
    try:
        from geoalchemy2.functions import ST_X, ST_Y
        result = await db.execute(
            select(
                Incident.id,
                Incident.incident_type,
                Incident.severity,
                Incident.description,
                Incident.source,
                Incident.started_at,
                ST_X(Incident.location_geom).label("lon"),
                ST_Y(Incident.location_geom).label("lat"),
            )
            .where(Incident.status == "active")
            .where(Incident.location_geom.isnot(None))
            .order_by(Incident.started_at.desc())
            .limit(200)
        )
        rows = result.all()
    except Exception:
        logger.exception("Failed to query incidents for map")
        rows = []

    features: list[dict] = []
    for row in rows:
        if row.lat is None or row.lon is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(row.lon), float(row.lat)]},
            "properties": {
                "id": row.id,
                "incident_type": row.incident_type,
                "severity": row.severity or 0,
                "description": row.description or "",
                "source": row.source or "",
                "started_at": row.started_at.isoformat() if row.started_at else None,
            },
        })

    return {"type": "FeatureCollection", "features": features}
