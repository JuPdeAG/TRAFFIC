"""SQLAlchemy 2.0 ORM models for Traffic AI Platform."""
from __future__ import annotations
import uuid
from datetime import date, datetime
from typing import Optional
from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean, Date, Float, ForeignKey, Integer, SmallInteger, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


class RoadSegment(Base):
    """A managed road segment with geometry."""
    __tablename__ = "road_segments"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    pilot: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    geom = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)
    length_m: Mapped[Optional[float]] = mapped_column(Float)
    speed_limit_kmh: Mapped[Optional[int]] = mapped_column(SmallInteger)
    road_class: Mapped[Optional[str]] = mapped_column(String(50))
    lanes: Mapped[Optional[int]] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())
    baselines: Mapped[list["SpeedBaseline"]] = relationship(back_populates="segment")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="segment")
    assets: Mapped[list["RoadAsset"]] = relationship(back_populates="segment")
    vehicle_tracks: Mapped[list["VehicleTrack"]] = relationship(back_populates="segment")


class SpeedBaseline(Base):
    """Statistical speed baseline per segment, hour, and day."""
    __tablename__ = "speed_baseline"
    __table_args__ = (UniqueConstraint("segment_id", "hour_of_day", "day_of_week"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment_id: Mapped[str] = mapped_column(ForeignKey("road_segments.id"), nullable=False)
    hour_of_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    local_hour_of_day: Mapped[Optional[int]] = mapped_column(SmallInteger)
    local_day_of_week: Mapped[Optional[int]] = mapped_column(SmallInteger)
    timezone: Mapped[Optional[str]] = mapped_column(String(64), default="UTC")
    avg_speed_kmh: Mapped[float] = mapped_column(Float, nullable=False)
    std_speed_kmh: Mapped[Optional[float]] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())
    segment: Mapped["RoadSegment"] = relationship(back_populates="baselines")


class Incident(Base):
    """Traffic incident tied to a segment."""
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pilot: Mapped[str] = mapped_column(String(50), nullable=False)
    incident_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[Optional[int]] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(50), default="active")
    location_geom = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    segment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("road_segments.id"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(String(100))
    external_id: Mapped[Optional[str]] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    segment: Mapped[Optional["RoadSegment"]] = relationship(back_populates="incidents")


class RoadAsset(Base):
    """Physical road asset (sign, barrier, light, etc.)."""
    __tablename__ = "road_assets"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    pilot: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(100), nullable=False)
    location_geom = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    segment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("road_segments.id"))
    installed_at: Mapped[Optional[date]] = mapped_column(Date)
    last_inspected: Mapped[Optional[date]] = mapped_column(Date)
    condition_score: Mapped[Optional[int]] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    segment: Mapped[Optional["RoadSegment"]] = relationship(back_populates="assets")
    detections: Mapped[list["DamageDetection"]] = relationship(back_populates="asset")
    tickets: Mapped[list["MaintenanceTicket"]] = relationship(back_populates="asset")


class DamageDetection(Base):
    """AI-detected damage on a road asset."""
    __tablename__ = "damage_detections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[Optional[str]] = mapped_column(ForeignKey("road_assets.id"))
    camera_id: Mapped[Optional[str]] = mapped_column(String(100))
    defect_class: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_json = mapped_column(JSONB, nullable=True)
    s3_annotated_key: Mapped[Optional[str]] = mapped_column(String(500))
    detected_at: Mapped[datetime] = mapped_column(default=func.now())
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_confirmed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    asset: Mapped[Optional["RoadAsset"]] = relationship(back_populates="detections")


class MaintenanceTicket(Base):
    """Maintenance work-order for a road asset."""
    __tablename__ = "maintenance_tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("road_assets.id"), nullable=False)
    detection_id: Mapped[Optional[int]] = mapped_column(ForeignKey("damage_detections.id"))
    pilot: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="open")
    priority: Mapped[int] = mapped_column(SmallInteger, default=3)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    assigned_to: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column()
    asset: Mapped["RoadAsset"] = relationship(back_populates="tickets")


class User(Base):
    """Application user."""
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(50), default="viewer")
    pilot_scope: Mapped[Optional[str]] = mapped_column(String(100))
    password_hash: Mapped[Optional[str]] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    last_login_at: Mapped[Optional[datetime]] = mapped_column()
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(back_populates="user")


class VehicleTrack(Base):
    """Individual vehicle observation from a camera."""
    __tablename__ = "vehicle_tracks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    track_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4)
    camera_id: Mapped[str] = mapped_column(String(100), nullable=False)
    segment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("road_segments.id"))
    vehicle_class: Mapped[Optional[str]] = mapped_column(String(50))
    observed_at: Mapped[datetime] = mapped_column(default=func.now())
    speed_kmh: Mapped[Optional[float]] = mapped_column(Float)
    direction: Mapped[Optional[int]] = mapped_column(SmallInteger)
    segment: Mapped[Optional["RoadSegment"]] = relationship(back_populates="vehicle_tracks")


class PushSubscription(Base):
    """Web Push subscription for a user."""
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    user: Mapped["User"] = relationship(back_populates="push_subscriptions")
