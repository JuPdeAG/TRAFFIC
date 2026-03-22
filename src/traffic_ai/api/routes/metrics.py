"""Aggregate metrics endpoints for dashboard charts."""
from __future__ import annotations
import asyncio
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


@router.get("/traffic-state")
async def traffic_state(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Current traffic state across all monitored cities and TomTom live feed.

    Queries the last 10 minutes from each city measurement concurrently and
    returns per-city averages plus a national congestion summary.
    """
    try:
        madrid_task = _query_city_state("madrid_traffic", "velocidad", "Madrid", "madrid")
        valencia_task = _query_city_state("valencia_traffic", "speed_kmh", "Valencia", "valencia")
        barcelona_task = _query_city_state("barcelona_traffic", "velocitat", "Barcelona", "barcelona")
        tomtom_task = _query_city_state("tomtom_flow", "current_speed", "TomTom", "tomtom")

        madrid_r, valencia_r, barcelona_r, tomtom_r = await asyncio.gather(
            madrid_task, valencia_task, barcelona_task, tomtom_task
        )

        cities = [madrid_r, valencia_r, barcelona_r, tomtom_r]

        # National: mean density excluding nulls
        densities = [c["avg_density"] for c in cities if c["avg_density"] is not None]
        avg_congestion = round(sum(densities) / len(densities), 1) if densities else None

        # TomTom live point count (reading_count already reflects records with density_score >= 0)
        tomtom_points_live = tomtom_r["reading_count"]

        return {
            "cities": cities,
            "national": {
                "avg_congestion": avg_congestion,
                "tomtom_points_live": tomtom_points_live,
            },
        }

    except Exception:
        logger.exception("Failed to query traffic state")
        return {
            "cities": [],
            "national": {"avg_congestion": None, "tomtom_points_live": 0},
            "note": "Data temporarily unavailable",
        }


@router.get("/metrics/congestion-trend")
async def congestion_trend(
    hours: int = Query(24, ge=1, le=168, description="Lookback window in hours"),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Hourly congestion percentage trend across all cities.

    Returns one entry per hour bucket with keys: time, madrid, valencia,
    barcelona, tomtom (each a density_score mean, or null if no data).
    Falls back to synthetic data derived from the HOURLY_SPEEDS profile when
    InfluxDB has no records yet.
    """

    async def _query_density_series(measurement: str) -> list[dict]:
        try:
            query = f"""
            from(bucket: "traffic_metrics")
              |> range(start: -{hours}h)
              |> filter(fn: (r) => r._measurement == "{measurement}")
              |> filter(fn: (r) => r._field == "density_score")
              |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
              |> sort(columns: ["_time"])
            """
            return await query_points(query)
        except Exception:
            logger.exception("Failed to query density series for %s", measurement)
            return []

    madrid_pts, valencia_pts, barcelona_pts, tomtom_pts = await asyncio.gather(
        _query_density_series("madrid_traffic"),
        _query_density_series("valencia_traffic"),
        _query_density_series("barcelona_traffic"),
        _query_density_series("tomtom_flow"),
    )

    def _extract(points: list[dict], city_key: str, merged: dict) -> None:
        for p in points:
            ts = p.get("_time")
            val = p.get("_value")
            if ts is None or val is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            label = ts.strftime("%H:%M") if isinstance(ts, datetime) else str(ts)
            merged.setdefault(label, {"time": label, "madrid": None, "valencia": None, "barcelona": None, "tomtom": None})
            merged[label][city_key] = round(float(val), 1)

    merged: dict[str, dict] = {}
    _extract(madrid_pts, "madrid", merged)
    _extract(valencia_pts, "valencia", merged)
    _extract(barcelona_pts, "barcelona", merged)
    _extract(tomtom_pts, "tomtom", merged)

    if not merged:
        return _synthetic_congestion(hours)

    return sorted(merged.values(), key=lambda r: r["time"])


# ── helpers ──────────────────────────────────────────────────────────────────


async def _query_city_state(
    measurement: str,
    speed_field: str,
    label: str,
    city_key: str,
) -> dict:
    """Query the last 10 minutes for a single city measurement.

    Returns a dict with avg_density, avg_speed_kmh, reading_count and
    last_updated.  All numeric fields are null when the query returns no rows.
    """
    query = f"""
    from(bucket: "traffic_metrics")
      |> range(start: -10m)
      |> filter(fn: (r) => r._measurement == "{measurement}")
      |> filter(fn: (r) => r._field == "density_score" or r._field == "{speed_field}")
      |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    """
    try:
        points = await query_points(query)
    except Exception:
        logger.exception("Failed to query city state for %s", measurement)
        points = []

    if not points:
        return {
            "city": city_key,
            "label": label,
            "avg_density": None,
            "avg_speed_kmh": None,
            "reading_count": 0,
            "last_updated": None,
        }

    densities = []
    speeds = []
    last_ts = None

    for p in points:
        d = p.get("density_score")
        s = p.get(speed_field)
        ts = p.get("_time")

        if d is not None:
            densities.append(float(d))
        if s is not None:
            speeds.append(float(s))
        if ts is not None:
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if last_ts is None or ts > last_ts:
                last_ts = ts

    avg_density = round(sum(densities) / len(densities), 1) if densities else None
    avg_speed = round(sum(speeds) / len(speeds), 1) if speeds else None

    if last_ts is not None:
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        last_updated = last_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        last_updated = None

    return {
        "city": city_key,
        "label": label,
        "avg_density": avg_density,
        "avg_speed_kmh": avg_speed,
        "reading_count": len(points),
        "last_updated": last_updated,
    }


def _synthetic_congestion(hours: int) -> list[dict]:
    """Return a realistic synthetic congestion pattern when no real data exists.

    Derives congestion percentage from HOURLY_SPEEDS: congestion = 100 - speed/90*100,
    clamped to [0, 100].  Applied uniformly to all four city keys with a small
    per-city offset so the chart lines are visually distinct.
    """
    HOURLY_SPEEDS = [
        85, 88, 90, 90, 88, 82, 65, 42, 38, 52,  # 00-09
        68, 72, 70, 68, 65, 58, 40, 38, 48, 62,  # 10-19
        70, 75, 80, 84,                             # 20-23
    ]
    CITY_OFFSETS = {"madrid": 0.0, "valencia": -3.0, "barcelona": 2.0, "tomtom": -1.5}

    now = datetime.now(timezone.utc)
    n = min(hours, 24)
    result = []
    for i in range(n):
        ts = now - timedelta(hours=n - 1 - i)
        base_speed = HOURLY_SPEEDS[ts.hour % 24]
        base_congestion = max(0.0, min(100.0, 100.0 - base_speed / 90.0 * 100.0))
        entry: dict = {"time": ts.strftime("%H:%M")}
        for city, offset in CITY_OFFSETS.items():
            entry[city] = round(max(0.0, min(100.0, base_congestion + offset)), 1)
        result.append(entry)
    return result


@router.get("/traffic-state")
async def traffic_state(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return live per-city traffic state aggregated from all city ingestors.

    Queries the last 10 minutes from InfluxDB for all four sources and
    returns average density, average speed, and reading count per city.
    """
    tasks = [
        _query_city_state("madrid_traffic",   "velocidad",     "Madrid",    "madrid"),
        _query_city_state("valencia_traffic",  "speed_kmh",     "Valencia",  "valencia"),
        _query_city_state("barcelona_traffic", "velocitat",     "Barcelona", "barcelona"),
        _query_city_state("tomtom_flow",       "current_speed", "National",  "tomtom"),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    cities = [r for r in results if isinstance(r, dict)]

    densities = [c["avg_density"] for c in cities if c["avg_density"] is not None]
    avg_congestion = round(sum(densities) / len(densities), 1) if densities else None

    tomtom_live = 0
    for c in cities:
        if c["city"] == "tomtom":
            tomtom_live = c["reading_count"]

    return {"cities": cities, "national": {"avg_congestion": avg_congestion, "tomtom_points_live": tomtom_live}}


async def _query_city_state(
    measurement: str, speed_field: str, label: str, city_key: str
) -> dict:
    """Query last 10 min of data for one city measurement."""
    density_q = f"""
    from(bucket: "traffic_metrics")
      |> range(start: -10m)
      |> filter(fn: (r) => r._measurement == "{measurement}")
      |> filter(fn: (r) => r._field == "density_score")
      |> mean()
    """
    speed_q = f"""
    from(bucket: "traffic_metrics")
      |> range(start: -10m)
      |> filter(fn: (r) => r._measurement == "{measurement}")
      |> filter(fn: (r) => r._field == "{speed_field}")
      |> mean()
    """
    count_q = f"""
    from(bucket: "traffic_metrics")
      |> range(start: -10m)
      |> filter(fn: (r) => r._measurement == "{measurement}")
      |> filter(fn: (r) => r._field == "density_score")
      |> count()
      |> sum()
    """
    try:
        d_rows, s_rows, c_rows = await asyncio.gather(
            query_points(density_q),
            query_points(speed_q),
            query_points(count_q),
            return_exceptions=True,
        )
        avg_density = _extract_value(d_rows)
        avg_speed   = _extract_value(s_rows)
        count       = int(_extract_value(c_rows) or 0)
    except Exception:
        avg_density = avg_speed = None
        count = 0

    return {
        "city": city_key,
        "label": label,
        "avg_density": round(float(avg_density), 1) if avg_density is not None else None,
        "avg_speed_kmh": round(float(avg_speed), 1) if avg_speed is not None else None,
        "reading_count": count,
        "last_updated": datetime.now(timezone.utc).isoformat() if count > 0 else None,
    }


def _extract_value(rows: object) -> float | None:
    if isinstance(rows, Exception) or not isinstance(rows, list) or not rows:
        return None
    val = rows[0].get("_value")
    return float(val) if val is not None else None


@router.get("/metrics/congestion-trend")
async def congestion_trend(
    hours: int = Query(24, ge=1, le=168),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Hourly average congestion % per city for the last N hours.

    Returns one dict per time bucket with keys: time, madrid, valencia,
    barcelona, tomtom.  Any city with no data in that bucket gets null.
    Falls back to synthetic data if InfluxDB has no readings yet.
    """
    measurements = [
        ("madrid_traffic",   "madrid"),
        ("valencia_traffic",  "valencia"),
        ("barcelona_traffic", "barcelona"),
        ("tomtom_flow",       "tomtom"),
    ]

    async def _query_series(measurement: str, key: str) -> tuple[str, list[dict]]:
        q = f"""
        from(bucket: "traffic_metrics")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r._measurement == "{measurement}")
          |> filter(fn: (r) => r._field == "density_score")
          |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
          |> sort(columns: ["_time"])
        """
        try:
            rows = await query_points(q)
            return key, rows
        except Exception:
            return key, []

    raw = await asyncio.gather(*[_query_series(m, k) for m, k in measurements])

    # Merge by time bucket
    merged: dict[str, dict] = {}
    has_any = False
    for city_key, rows in raw:
        for row in rows:
            ts = row.get("_time")
            val = row.get("_value")
            if ts is None or val is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            label = ts.strftime("%H:%M") if isinstance(ts, datetime) else str(ts)
            if label not in merged:
                merged[label] = {"time": label, "madrid": None, "valencia": None, "barcelona": None, "tomtom": None}
            merged[label][city_key] = round(float(val), 1)
            has_any = True

    if has_any:
        return sorted(merged.values(), key=lambda r: r["time"])

    return _synthetic_congestion(hours)


def _synthetic_congestion(hours: int) -> list[dict]:
    """Synthetic congestion pattern (% scale) until real data arrives."""
    # Typical Madrid M-30 speed profile → congestion conversion
    HOURLY_SPEEDS = [
        85, 88, 90, 90, 88, 82, 65, 42, 38, 52,
        68, 72, 70, 68, 65, 58, 40, 38, 48, 62,
        70, 75, 80, 84,
    ]
    FREE_FLOW = 90.0
    now = datetime.now(timezone.utc)
    result = []
    n = min(hours, 24)
    for i in range(n):
        ts = now - timedelta(hours=n - 1 - i)
        spd = HOURLY_SPEEDS[ts.hour % 24]
        cong = round(max(0.0, min(100.0, (1 - spd / FREE_FLOW) * 100)), 1)
        result.append({
            "time": ts.strftime("%H:%M"),
            "madrid": cong,
            "valencia": round(cong * 0.82, 1),
            "barcelona": round(cong * 0.91, 1),
            "tomtom": None,
        })
    return result


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
