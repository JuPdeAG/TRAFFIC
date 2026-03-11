"""Road segment CRUD endpoints."""
from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from traffic_ai.api.deps import get_current_user
from traffic_ai.db.database import get_db
from traffic_ai.models.orm import RoadSegment, User
from traffic_ai.models.schemas import RoadSegmentOut

router = APIRouter()


@router.get("/segments", response_model=list[RoadSegmentOut])
async def list_segments(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
    pilot: str | None = Query(None, description="Filter by pilot name"),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
) -> list[RoadSegmentOut]:
    """List road segments with optional pilot filter and pagination."""
    stmt = select(RoadSegment)
    if pilot:
        stmt = stmt.where(RoadSegment.pilot == pilot)
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [RoadSegmentOut.model_validate(s) for s in result.scalars().all()]


@router.get("/segments/{segment_id}", response_model=RoadSegmentOut)
async def get_segment(
    segment_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> RoadSegmentOut:
    """Get a single road segment by ID."""
    result = await db.execute(select(RoadSegment).where(RoadSegment.id == segment_id))
    segment = result.scalar_one_or_none()
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found")
    return RoadSegmentOut.model_validate(segment)
