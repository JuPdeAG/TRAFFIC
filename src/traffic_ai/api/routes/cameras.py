"""Camera metrics endpoints — live data from InfluxDB camera ingestors."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from traffic_ai.api.deps import get_current_user
from traffic_ai.db.influx import query_points
from traffic_ai.models.orm import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/cameras")
async def list_cameras(
    source: str | None = Query(None, description="Filter by source: dgt | madrid"),
    online_only: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Return the latest metric snapshot for each known camera.

    Queries InfluxDB measurements `dgt_camera` and `madrid_camera` for the
    most recent reading per camera_id within the last 30 minutes.
    """
    results = []

    measurements = _resolve_measurements(source)
    for measurement, src_label in measurements:
        try:
            rows = await _query_latest_camera_metrics(measurement, limit)
            for row in rows:
                cam_id = row.get("camera_id", row.get("_measurement", "unknown"))
                online = row.get("camera_online", True)
                if online_only and not online:
                    continue
                results.append({
                    "id": cam_id,
                    "source": src_label,
                    "road": row.get("road", row.get("road_id", "")),
                    "vehicle_count": int(row.get("vehicle_count") or 0),
                    "density_score": round(float(row.get("density_score") or 0), 1),
                    "density_level": _density_level(float(row.get("density_score") or 0)),
                    "camera_online": bool(online),
                    "last_seen": row.get("_time", datetime.now(timezone.utc).isoformat()),
                })
        except Exception:
            logger.exception("Failed to query %s camera metrics", measurement)

    if not results:
        return _empty_camera_list(source)

    results.sort(key=lambda c: c["density_score"], reverse=True)
    return results[:limit]


@router.get("/cameras/stats")
async def camera_stats(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return aggregate camera statistics."""
    try:
        cameras = await list_cameras(
            source=None, online_only=False, limit=1000, current_user=current_user
        )
        total = len(cameras)
        online = sum(1 for c in cameras if c["camera_online"])
        offline = total - online
        avg_density = (
            sum(c["density_score"] for c in cameras) / total if total else 0
        )
        return {
            "total": total,
            "online": online,
            "offline": offline,
            "avg_density_score": round(avg_density, 1),
        }
    except Exception:
        logger.exception("Failed to compute camera stats")
        return {"total": 0, "online": 0, "offline": 0, "avg_density_score": 0.0}


# ── helpers ──────────────────────────────────────────────────────────────────


def _resolve_measurements(source: str | None) -> list[tuple[str, str]]:
    if source == "dgt":
        return [("dgt_camera", "dgt")]
    if source == "madrid":
        return [("madrid_camera", "madrid")]
    return [("dgt_camera", "dgt"), ("madrid_camera", "madrid")]


async def _query_latest_camera_metrics(measurement: str, limit: int) -> list[dict]:
    """Query most recent reading per camera from InfluxDB."""
    query = f"""
    from(bucket: "traffic_metrics")
      |> range(start: -30m)
      |> filter(fn: (r) => r._measurement == "{measurement}")
      |> last()
      |> limit(n: {limit})
    """
    return await query_points(query)


def _density_level(score: float) -> str:
    if score < 15:
        return "free_flow"
    if score < 35:
        return "light"
    if score < 55:
        return "moderate"
    if score < 75:
        return "heavy"
    return "gridlock"


def _empty_camera_list(source: str | None) -> list[dict]:
    """Return stub entries so the UI shows something before ingestion starts."""
    sources = ["dgt", "madrid"] if source is None else [source]
    stubs = []
    for src in sources:
        for i in range(1, 4):
            stubs.append({
                "id": f"{src}_cam_{i:03d}",
                "source": src,
                "road": "",
                "vehicle_count": 0,
                "density_score": 0.0,
                "density_level": "unknown",
                "camera_online": False,
                "last_seen": None,
            })
    return stubs
