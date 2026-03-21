"""Congestion prediction endpoints — LSTM ONNX inference with heuristic fallback."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from traffic_ai.api.deps import get_current_user
from traffic_ai.db.database import get_db
from traffic_ai.models.orm import RoadSegment, User
from traffic_ai.models.schemas import PredictionOut, PredictionRequest

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/predict/congestion", response_model=PredictionOut)
async def predict_congestion(
    request: PredictionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> PredictionOut:
    """Predict congestion for a segment using the LSTM ONNX model.

    Falls back to a baseline-derived heuristic when the model file is absent
    (e.g. before training has been run) or when onnxruntime is not installed.
    """
    result = await db.execute(select(RoadSegment).where(RoadSegment.id == request.segment_id))
    segment = result.scalar_one_or_none()
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found")

    # Try LSTM inference first
    prediction = await _lstm_predict(request.segment_id, request.horizon_minutes, segment)

    return PredictionOut(
        segment_id=request.segment_id,
        predicted_speed_kmh=prediction["predicted_speed_kmh"],
        congestion_level=prediction["congestion_level"],
        confidence=prediction["confidence"],
        horizon_minutes=request.horizon_minutes,
        predicted_at=datetime.now(timezone.utc),
    )


@router.get("/predict/history/{segment_id}", response_model=list[PredictionOut])
async def prediction_history(
    segment_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> list[PredictionOut]:
    """Return historical predictions for a segment (stored by the prediction task)."""
    result = await db.execute(select(RoadSegment).where(RoadSegment.id == segment_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    # Predictions are logged to InfluxDB; return empty list until query is wired
    return []


# ── inference helper ─────────────────────────────────────────────────────────


async def _lstm_predict(
    segment_id: str,
    horizon_minutes: int,
    segment: RoadSegment,
) -> dict:
    """Build the input sequence from InfluxDB and run LSTM inference."""
    try:
        from traffic_ai.db.influx import query_points  # noqa: PLC0415
        from traffic_ai.ml.congestion_model import (  # noqa: PLC0415
            build_sequence_from_influx,
            predict_congestion,
        )

        # Fetch last 60 min of sensor readings (12 × 5-min steps)
        sensor_query = f"""
        from(bucket: "traffic_metrics")
          |> range(start: -1h)
          |> filter(fn: (r) => r._measurement == "loop_detector")
          |> filter(fn: (r) => r.segment_id == "{segment_id}")
          |> filter(fn: (r) => r._field == "speed_kmh" or r._field == "occupancy_pct" or r._field == "flow_veh_per_min")
          |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
          |> sort(columns: ["_time"])
        """
        sensor_pts = await query_points(sensor_query)

        # Fetch latest weather
        wx_query = """
        from(bucket: "traffic_metrics")
          |> range(start: -1h)
          |> filter(fn: (r) => r._measurement == "weather")
          |> last()
        """
        wx_pts = await query_points(wx_query)
        wx_vals: dict = {}
        for p in wx_pts:
            field = p.get("_field", "")
            val = p.get("_value")
            if val is not None:
                wx_vals[field] = float(val)

        sequence = build_sequence_from_influx(sensor_pts, wx_vals)
        if sequence is not None:
            return predict_congestion(sequence, horizon_minutes)

    except Exception as exc:
        logger.debug("LSTM inference path failed (%s), using baseline heuristic", exc)

    # Fallback: derive from speed limit and baseline
    return _baseline_predict(segment, horizon_minutes)


def _baseline_predict(segment: RoadSegment, horizon_minutes: int) -> dict:
    """Simple baseline prediction from speed limit when LSTM is unavailable."""
    base_speed = float(segment.speed_limit_kmh or 50)
    # Assume moderate congestion as conservative default
    predicted_speed = base_speed * 0.75
    ratio = predicted_speed / base_speed
    if ratio >= 0.85:
        level = "free_flow"
    elif ratio >= 0.65:
        level = "moderate"
    elif ratio >= 0.40:
        level = "heavy"
    else:
        level = "gridlock"
    return {
        "predicted_speed_kmh": round(predicted_speed, 1),
        "congestion_level": level,
        "confidence": 0.35,  # Low confidence — no real data available
        "model": "baseline_heuristic",
    }
