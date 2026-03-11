"""Road asset endpoints."""
from __future__ import annotations
from datetime import date, datetime
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from traffic_ai.api.deps import get_current_user
from traffic_ai.db.database import get_db
from traffic_ai.models.orm import RoadAsset, User

router = APIRouter()


class AssetOut(BaseModel):
    """Response schema for a road asset."""
    id: str
    pilot: str
    asset_type: str
    segment_id: Optional[str] = None
    condition_score: Optional[int] = None
    installed_at: Optional[date] = None
    last_inspected: Optional[date] = None
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


@router.get("/assets", response_model=list[AssetOut])
async def list_assets(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
    pilot: str | None = Query(None),
    asset_type: str | None = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
) -> list[AssetOut]:
    """List road assets with optional filters."""
    stmt = select(RoadAsset)
    if pilot:
        stmt = stmt.where(RoadAsset.pilot == pilot)
    if asset_type:
        stmt = stmt.where(RoadAsset.asset_type == asset_type)
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [AssetOut.model_validate(a) for a in result.scalars().all()]


@router.get("/assets/{asset_id}", response_model=AssetOut)
async def get_asset(
    asset_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User = Depends(get_current_user),
) -> AssetOut:
    """Get a single road asset by ID."""
    result = await db.execute(select(RoadAsset).where(RoadAsset.id == asset_id))
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetOut.model_validate(asset)
