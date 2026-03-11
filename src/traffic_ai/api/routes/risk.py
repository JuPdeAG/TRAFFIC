"""Risk scoring endpoints."""
from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from traffic_ai.analytics.risk_scorer import RiskScoringEngine
from traffic_ai.api.deps import get_current_user
from traffic_ai.db.database import get_db
from traffic_ai.models.orm import RoadSegment, User

router = APIRouter()


@router.get("/risk/summary")
async def risk_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Return risk scores for all segments."""
    result = await db.execute(select(RoadSegment.id))
    segment_ids = [row[0] for row in result.all()]
    engine = RiskScoringEngine(db=db)
    summaries = []
    for sid in segment_ids[:100]:
        score = await engine.compute(sid)
        summaries.append({
            "segment_id": sid,
            "score": score,
            "level": RiskScoringEngine.score_to_level(score),
        })
    return summaries


@router.get("/risk/{segment_id}")
async def get_risk_score(
    segment_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> dict:
    """Compute and return the current risk score for a segment."""
    result = await db.execute(select(RoadSegment).where(RoadSegment.id == segment_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    engine = RiskScoringEngine(db=db)
    return await engine.compute_with_explanation(segment_id)


@router.get("/risk/{segment_id}/explain")
async def explain_risk_score(
    segment_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> dict:
    """Detailed factor-by-factor explanation of the risk score."""
    result = await db.execute(select(RoadSegment).where(RoadSegment.id == segment_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    engine = RiskScoringEngine(db=db)
    explanation = await engine.compute_with_explanation(segment_id)
    explanation["shap"] = await engine.explain_with_shap(segment_id)
    return explanation
