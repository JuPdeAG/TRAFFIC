"""Application configuration with hardware-adaptive profiles."""
from __future__ import annotations
import psutil
from dataclasses import dataclass, field
from typing import Literal
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global application settings loaded from environment / .env file."""
    profile: Literal["lite", "prosumer", "balanced", "full", "benchmark"] = "balanced"
    database_url: str = "postgresql+asyncpg://traffic:traffic@postgres:5432/traffic_ai"
    influx_url: str = "http://influxdb:8086"
    influx_token: str = ""
    influx_org: str = "traffic-ai"
    influx_bucket: str = "traffic_metrics"
    redis_url: str = "redis://redis:6379/0"
    celery_concurrency: int = 8
    frame_bucket: str = "traffic-frames"
    model_bucket: str = "traffic-models"
    s3_bucket: str = ""
    aws_region: str = "us-east-1"
    gdpr_mode: bool = False
    secret_key: str = "change-me"
    # For production, consider RS256 with RSA key pair
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    environment: str = "development"
    # Comma-separated list of allowed CORS origins. Use "*" for dev, exact origins for prod.
    cors_origins: str = "http://localhost:5173"
    aemet_api_key: str = ""
    tomtom_api_key: str = ""
    mapbox_token: str = ""
    loop_detector_urls: str = ""
    noaa_stations: str = ""
    aemet_stations: str = ""
    camera_urls: str = ""
    # JSON array of {lat, lon, name} objects for Open-Meteo live weather ingestor.
    # Defaults to Madrid city centre when empty.
    open_meteo_locations: str = ""
    # Webhook URL for high-severity event notifications. Can also be set at
    # runtime via PATCH /api/v1/settings (stored in Redis).
    webhook_url: str = ""
    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def loop_detector_url_list(self) -> list[str]:
        """Parse comma-separated loop detector URLs into a list."""
        return [u.strip() for u in self.loop_detector_urls.split(",") if u.strip()]

    @property
    def noaa_station_list(self) -> list[str]:
        """Parse comma-separated NOAA station IDs into a list."""
        return [s.strip() for s in self.noaa_stations.split(",") if s.strip()]

    @property
    def aemet_station_list(self) -> list[str]:
        """Parse comma-separated AEMET station IDs into a list."""
        return [s.strip() for s in self.aemet_stations.split(",") if s.strip()]

    @property
    def camera_url_list(self) -> list[str]:
        """Parse comma-separated camera URLs into a list."""
        return [u.strip() for u in self.camera_urls.split(",") if u.strip()]

settings = Settings()


@dataclass
class ProfileConfig:
    """Hardware-adaptive profile configuration."""
    name: str
    max_cameras: int
    max_loop_detectors: int
    celery_concurrency: int
    enable_gpu: bool
    enable_onnx: bool
    influx_retention_days: int
    risk_compute_interval_s: int
    baseline_recalc_interval_s: int
    weather_poll_interval_s: int
    max_frame_batch_size: int
    throttle_cpu_pct: float = 85.0
    throttle_mem_pct: float = 85.0
    extra: dict = field(default_factory=dict)


PROFILES: dict[str, ProfileConfig] = {
    "lite": ProfileConfig(
        name="lite", max_cameras=2, max_loop_detectors=10, celery_concurrency=2,
        enable_gpu=False, enable_onnx=False, influx_retention_days=7,
        risk_compute_interval_s=300, baseline_recalc_interval_s=86400,
        weather_poll_interval_s=1800, max_frame_batch_size=1,
        throttle_cpu_pct=70.0, throttle_mem_pct=70.0,
    ),
    "prosumer": ProfileConfig(
        name="prosumer", max_cameras=8, max_loop_detectors=50, celery_concurrency=12,
        enable_gpu=True, enable_onnx=True, influx_retention_days=90,
        risk_compute_interval_s=60, baseline_recalc_interval_s=3600,
        weather_poll_interval_s=600, max_frame_batch_size=8,
        throttle_cpu_pct=85.0, throttle_mem_pct=85.0,
    ),
    "balanced": ProfileConfig(
        name="balanced", max_cameras=4, max_loop_detectors=25, celery_concurrency=8,
        enable_gpu=False, enable_onnx=True, influx_retention_days=30,
        risk_compute_interval_s=120, baseline_recalc_interval_s=7200,
        weather_poll_interval_s=900, max_frame_batch_size=4,
        throttle_cpu_pct=80.0, throttle_mem_pct=80.0,
    ),
    "full": ProfileConfig(
        name="full", max_cameras=16, max_loop_detectors=100, celery_concurrency=16,
        enable_gpu=True, enable_onnx=True, influx_retention_days=365,
        risk_compute_interval_s=30, baseline_recalc_interval_s=1800,
        weather_poll_interval_s=300, max_frame_batch_size=16,
        throttle_cpu_pct=90.0, throttle_mem_pct=90.0,
    ),
    "benchmark": ProfileConfig(
        name="benchmark", max_cameras=32, max_loop_detectors=200, celery_concurrency=32,
        enable_gpu=True, enable_onnx=True, influx_retention_days=3,
        risk_compute_interval_s=10, baseline_recalc_interval_s=600,
        weather_poll_interval_s=120, max_frame_batch_size=32,
        throttle_cpu_pct=95.0, throttle_mem_pct=95.0,
    ),
}


def get_profile() -> ProfileConfig:
    """Return the active profile configuration."""
    return PROFILES[settings.profile]


class RuntimeResourceManager:
    """Monitors system resources and throttles workloads.

    Bug-fix: uses OR (not AND) so either CPU or memory spike triggers throttling.
    """
    def __init__(self, profile: ProfileConfig | None = None) -> None:
        self.profile = profile or get_profile()

    def cpu_percent(self) -> float:
        """Return current CPU utilisation percentage."""
        return psutil.cpu_percent(interval=0.1)

    def memory_percent(self) -> float:
        """Return current memory utilisation percentage."""
        return psutil.virtual_memory().percent

    def should_throttle(self) -> bool:
        """Return True if system is above profile resource limits (OR logic)."""
        cpu = self.cpu_percent()
        mem = self.memory_percent()
        return cpu > self.profile.throttle_cpu_pct or mem > self.profile.throttle_mem_pct

    def available_concurrency(self) -> int:
        """Return allowed concurrent tasks."""
        if self.should_throttle():
            return max(1, self.profile.celery_concurrency // 2)
        return self.profile.celery_concurrency
