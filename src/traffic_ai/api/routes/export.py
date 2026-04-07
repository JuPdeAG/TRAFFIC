"""EC2 historical data export endpoint.

Returns InfluxDB data as Parquet files in a ZIP archive.
One Parquet per source, hourly aggregated.

Endpoint:
  GET /api/v1/export/status          — latest available timestamp per source
  GET /api/v1/export/parquet         — download ZIP of Parquet files
    ?sources=madrid_traffic,barcelona_traffic,valencia_traffic,tomtom_flow
    &from_date=2026-04-01
    &to_date=2026-04-07            (optional, defaults to now)
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from traffic_ai.api.deps import get_current_user
from traffic_ai.db.influx import query_points
from traffic_ai.models.user import User

router = APIRouter(tags=["Export"])

MAX_DAYS = 90

# Measurement config: key → InfluxDB measurement name, entity tag, fields
_SOURCES: dict[str, dict] = {
    "madrid_traffic": {
        "measurement": "madrid_traffic",
        "tag": "tramo_id",
        "fields": ["speed_kmh", "load_pct", "occupancy_pct", "density_score", "estado"],
    },
    "barcelona_traffic": {
        "measurement": "barcelona_traffic",
        "tag": "tram_id",
        "fields": ["density_score", "density_score_forecast", "speed_kmh", "estat", "estat_forecast"],
    },
    "valencia_traffic": {
        "measurement": "valencia_traffic",
        "tag": "seg_id",
        "fields": ["density_score", "estado"],
    },
    "tomtom_flow": {
        "measurement": "tomtom_flow",
        "tag": "point_id",
        "fields": ["current_speed", "free_flow_speed", "density_score", "confidence"],
    },
}


@router.get("/export/status")
async def export_status(
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str | None]:
    """Return the latest available timestamp for each source in InfluxDB."""
    result: dict[str, str | None] = {}
    for key, cfg in _SOURCES.items():
        query = f"""
from(bucket: "traffic_metrics")
  |> range(start: -90d)
  |> filter(fn: (r) => r._measurement == "{cfg['measurement']}")
  |> last()
  |> keep(columns: ["_time"])
"""
        try:
            rows = await query_points(query)
            if rows:
                times = [r.get("_time") for r in rows if r.get("_time") is not None]
                if times:
                    latest = max(times)
                    result[key] = latest.isoformat() if hasattr(latest, "isoformat") else str(latest)
                else:
                    result[key] = None
            else:
                result[key] = None
        except Exception:
            result[key] = None
    return result


@router.get("/export/parquet")
async def export_parquet(
    current_user: Annotated[User, Depends(get_current_user)],
    from_date: str = Query(..., description="Start date, ISO format: 2026-04-01"),
    to_date: str | None = Query(default=None, description="End date, ISO format. Defaults to now."),
    sources: str = Query(
        default="madrid_traffic,barcelona_traffic,valencia_traffic,tomtom_flow",
        description="Comma-separated source keys",
    ),
) -> StreamingResponse:
    """Stream a ZIP archive containing one Parquet file per requested source.

    Data is aggregated to hourly means. Maximum range is 90 days.
    """
    try:
        from_dt = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid from_date: {from_date!r}")

    if to_date:
        try:
            to_dt = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid to_date: {to_date!r}")
    else:
        to_dt = datetime.now(timezone.utc)

    if (to_dt - from_dt).days > MAX_DAYS:
        raise HTTPException(status_code=400, detail=f"Date range exceeds {MAX_DAYS} days maximum.")

    if from_dt >= to_dt:
        raise HTTPException(status_code=400, detail="from_date must be before to_date.")

    requested = [s.strip() for s in sources.split(",") if s.strip() in _SOURCES]
    if not requested:
        raise HTTPException(status_code=400, detail=f"No valid sources. Choose from: {', '.join(_SOURCES)}")

    from_str = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_str = to_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for key in requested:
            cfg = _SOURCES[key]
            measurement = cfg["measurement"]
            tag = cfg["tag"]
            fields = cfg["fields"]

            fields_filter = " or ".join(f'r._field == "{f}"' for f in fields)
            query = f"""
from(bucket: "traffic_metrics")
  |> range(start: {from_str}, stop: {to_str})
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> filter(fn: (r) => {fields_filter})
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time", "{tag}"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
"""
            try:
                rows = await query_points(query)
            except Exception:
                continue

            if not rows:
                continue

            df = pd.DataFrame(rows)

            # Keep timestamp, entity tag, and any field columns that exist
            keep = ["_time", tag] + [f for f in fields if f in df.columns]
            df = df[[c for c in keep if c in df.columns]].rename(columns={"_time": "timestamp"})
            df = df.dropna(subset=["timestamp"])

            pq_buf = io.BytesIO()
            df.to_parquet(pq_buf, index=False, engine="pyarrow", compression="snappy")
            zf.writestr(f"{key}.parquet", pq_buf.getvalue())

    zip_buf.seek(0)
    fname = f"traffic_export_{from_dt.strftime('%Y%m%d')}_{to_dt.strftime('%Y%m%d')}.zip"
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )
