"""Pydantic v2 schemas for API request/response models."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class RoadSegmentOut(BaseModel):
    """Response schema for a road segment."""
    id: str
    pilot: str
    name: Optional[str] = None
    length_m: Optional[float] = None
    speed_limit_kmh: Optional[int] = None
    road_class: Optional[str] = None
    lanes: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class RiskScoreOut(BaseModel):
    """Response schema for a computed risk score."""
    segment_id: str
    score: float = Field(ge=0, le=100)
    level: str
    factors: dict[str, float] = {}
    computed_at: datetime
    model_config = {"from_attributes": True}


class PredictionRequest(BaseModel):
    """Request body for congestion prediction."""
    segment_id: str
    horizon_minutes: int = Field(default=30, ge=5, le=1440)


class PredictionOut(BaseModel):
    """Response schema for congestion prediction."""
    segment_id: str
    predicted_speed_kmh: float
    congestion_level: str
    confidence: float
    horizon_minutes: int
    predicted_at: datetime
    model_config = {"from_attributes": True}


class IncidentOut(BaseModel):
    """Response schema for an incident."""
    id: int
    pilot: str
    incident_type: str
    severity: Optional[int] = None
    status: str
    segment_id: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class DamageDetectionOut(BaseModel):
    """Response schema for a damage detection."""
    id: int
    asset_id: Optional[str] = None
    camera_id: Optional[str] = None
    defect_class: str
    confidence: float
    bbox_json: Optional[dict[str, Any]] = None
    detected_at: datetime
    reviewed: bool
    is_confirmed: Optional[bool] = None
    model_config = {"from_attributes": True}


class TicketOut(BaseModel):
    """Response schema for a maintenance ticket."""
    id: int
    asset_id: str
    detection_id: Optional[int] = None
    pilot: str
    status: str
    priority: int
    title: str
    description: Optional[str] = None
    assigned_to: Optional[uuid.UUID] = None
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class TicketUpdate(BaseModel):
    """Request body for updating a ticket status."""
    status: str
    resolution_note: Optional[str] = None


class UserOut(BaseModel):
    """Response schema for a user (no password hash)."""
    id: uuid.UUID
    email: str
    name: Optional[str] = None
    role: str
    pilot_scope: Optional[str] = None
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Response schema for authentication tokens."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
