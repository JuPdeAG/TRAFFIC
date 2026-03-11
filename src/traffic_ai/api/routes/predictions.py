"""Congestion prediction endpoints.

TODO: Replace placeholder predictions with real LSTM/ONNX model inference.
The LSTM model pipeline is pending implementation (spec §4.1).
Current responses are meaningful placeholders that match the expected schema.
"""
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
    """Predict congestion for a segment.

    TODO: Integrate ONNX runtime with trained LSTM model for real predictions.
    Currently returns a placeholder prediction with moderate confidence.
    """
    result = await db.execute(select(RoadSegment).where(RoadSegment.id == request.segment_id))
    segment = result.scalar_one_or_none()
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found")

    # Placeholder: use speed limit as basis for predicted speed
    base_speed = segment.speed_limit_kmh or 50
    predicted_speed = base_speed * 0.75  # Assume moderate congestion as default

    # Determine congestion level from predicted speed ratio
    ratio = predicted_speed / base_speed if base_speed > 0 else 0.5
    if ratio >= 0.8:
        level = "free_flow"
    elif ratio >= 0.6:
        level = "moderate"
    elif ratio >= 0.4:
        level = "heavy"
    else:
        level = "severe"

    logger.info(
        "Prediction stub for segment %s: speed=%.1f, level=%s (LSTM model pending)",
        request.segment_id, predicted_speed, level,
    )

    return PredictionOut(
        segment_id=request.segment_id,
        predicted_speed_kmh=round(predicted_speed, 1),
        congestion_level=level,
        confidence=0.50,  # Low confidence for placeholder
        horizon_minutes=request.horizon_minutes,
        predicted_at=datetime.now(timezone.utc),
    )


@router.get("/predict/history/{segment_id}", response_model=list[PredictionOut])
async def prediction_history(
    segment_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> list[PredictionOut]:
    """Return historical predictions for a segment.

    TODO: Query stored predictions from the database once the LSTM pipeline
    is operational and predictions are being persisted.
    """
    result = await db.execute(select(RoadSegment).where(RoadSegment.id == segment_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    # No stored predictions yet — LSTM pipeline pending
    return []
