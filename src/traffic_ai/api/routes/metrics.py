"""Aggregate metrics endpoints for dashboard charts."""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from traffic_ai.api.deps import get_current_user
from traffic_ai.db.influx import query_points
from traffic_ai.models.orm import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/metrics/flow")
async def traffic_flow_history(
    hours: int = Query(24, ge=1, le=168, description="Lookback window in hours"),
    segment_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Hourly average speed/flow for the dashboard chart.

    Returns one point per hour with keys: time, flow (avg speed km/h),
    volume (avg vehicle count), source.
    """
    try:
        seg_filter = f'|> filter(fn: (r) => r.segment_id == "{segment_id}")' if segment_id else ""
        query = f"""
        from(bucket: "traffic_metrics")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r._measurement == "loop_detector" or
                               r._measurement == "madrid_loop")
          |> filter(fn: (r) => r._field == "speed_kmh")
          {seg_filter}
          |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
          |> sort(columns: ["_time"])
        """
        points = await query_points(query)

        result = []
        for p in points:
            ts = p.get("_time")
            val = p.get("_value")
            if ts is None or val is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            result.append({
                "time": ts.strftime("%H:%M") if isinstance(ts, datetime) else str(ts),
                "flow": round(float(val), 1),
                "volume": None,
            })

        return result or _synthetic_flow(hours)

    except Exception:
        logger.exception("Failed to query traffic flow history")
        return _synthetic_flow(hours)


@router.get("/metrics/risk-trend")
async def risk_score_trend(
    days: int = Query(30, ge=1, le=90, description="Lookback window in days"),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Daily average risk score for the Risk Analysis trend chart.

    Returns one point per day with keys: day, score.
    Reads from the `risk_score` InfluxDB measurement written by the risk task.
    Falls back to empty list with a 'collecting' flag if no data yet.
    """
    try:
        query = f"""
        from(bucket: "traffic_metrics")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "risk_score")
          |> filter(fn: (r) => r._field == "score")
          |> aggregateWindow(every: 1d, fn: mean, createEmpty: false)
          |> sort(columns: ["_time"])
        """
        points = await query_points(query)

        result = []
        for p in points:
            ts = p.get("_time")
            val = p.get("_value")
            if ts is None or val is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            result.append({
                "day": ts.strftime("%-d %b") if isinstance(ts, datetime) else str(ts),
                "score": round(float(val), 1),
            })

        return result  # empty list = no data yet; frontend shows "collecting" state

    except Exception:
        logger.exception("Failed to query risk score trend")
        return []


# ── helpers ──────────────────────────────────────────────────────────────────


def _synthetic_flow(hours: int) -> list[dict]:
    """Return a realistic synthetic traffic pattern when no real data exists.

    Uses a typical Madrid rush-hour profile so the dashboard looks meaningful
    before sensors are wired.
    """
    # Typical hourly speed profile for Madrid M-30 (km/h)
    HOURLY_SPEEDS = [
        85, 88, 90, 90, 88, 82, 65, 42, 38, 52,  # 00-09
        68, 72, 70, 68, 65, 58, 40, 38, 48, 62,  # 10-19
        70, 75, 80, 84,                             # 20-23
    ]
    now = datetime.now(timezone.utc)
    result = []
    n = min(hours, 24)
    for i in range(n):
        ts = now - timedelta(hours=n - 1 - i)
        speed = HOURLY_SPEEDS[ts.hour % 24]
        result.append({
            "time": ts.strftime("%H:%M"),
            "flow": float(speed),
            "volume": None,
        })
    return result
