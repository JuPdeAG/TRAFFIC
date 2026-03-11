"""Risk scoring engine -- 7-factor model for road segment risk assessment."""
from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS: dict[str, float] = {
    "speed_deviation": 0.22,
    "incident_proximity": 0.18,
    "flow_density": 0.18,
    "historical_baseline": 0.13,
    "infrastructure_health": 0.09,
    "time_day_pattern": 0.10,
    "weather": 0.10,
}


@dataclass
class RiskFactors:
    """Individual risk factor scores (0-100 each)."""
    speed_deviation: float = 0.0
    incident_proximity: float = 0.0
    flow_density: float = 0.0
    historical_baseline: float = 0.0
    infrastructure_health: float = 0.0
    time_day_pattern: float = 0.0
    weather: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "speed_deviation": self.speed_deviation,
            "incident_proximity": self.incident_proximity,
            "flow_density": self.flow_density,
            "historical_baseline": self.historical_baseline,
            "infrastructure_health": self.infrastructure_health,
            "time_day_pattern": self.time_day_pattern,
            "weather": self.weather,
        }


class RiskScoringEngine:
    """Computes composite risk scores using 7 weighted factors.

    Accepts an async database session for querying PostgreSQL and uses
    InfluxDB for time-series factor calculations.
    """
    def __init__(self, db: AsyncSession | None = None, weights: dict[str, float] | None = None) -> None:
        self.db = db
        self.weights = weights or DEFAULT_WEIGHTS.copy()

    async def compute(self, segment_id: str) -> float:
        """Compute composite risk score (0-100) for a segment."""
        factors = await self._gather_factors(segment_id)
        score = self._weighted_sum(factors)
        return round(min(max(score, 0.0), 100.0), 2)

    async def compute_with_explanation(self, segment_id: str) -> dict[str, Any]:
        """Compute risk score with per-factor breakdown."""
        factors = await self._gather_factors(segment_id)
        score = round(min(max(self._weighted_sum(factors), 0.0), 100.0), 2)
        return {
            "segment_id": segment_id,
            "score": score,
            "level": self.score_to_level(score),
            "factors": factors.as_dict(),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _weighted_sum(self, factors: RiskFactors) -> float:
        fd = factors.as_dict()
        return sum(fd[n] * self.weights.get(n, 0.0) for n in fd)

    @staticmethod
    def score_to_level(score: float) -> str:
        """Convert a numeric risk score to a severity level string."""
        if score >= 75:
            return "critical"
        if score >= 50:
            return "high"
        if score >= 25:
            return "medium"
        return "low"

    # Keep backward compatibility
    _score_to_level = score_to_level

    async def _gather_factors(self, segment_id: str) -> RiskFactors:
        """Gather all 7 risk factors for a segment."""
        factors = RiskFactors()
        for attr, calc in [
            ("speed_deviation", self._calc_speed_deviation),
            ("incident_proximity", self._calc_incident_proximity),
            ("flow_density", self._calc_flow_density),
            ("time_day_pattern", self._calc_time_factor),
            ("historical_baseline", self._calc_historical_baseline),
            ("infrastructure_health", self._calc_infrastructure_health),
            ("weather", self._calc_weather),
        ]:
            try:
                setattr(factors, attr, await calc(segment_id))
            except Exception:
                logger.exception("Error calculating %s for %s", attr, segment_id)
        return factors

    async def _calc_speed_deviation(self, segment_id: str) -> float:
        """Query recent speed readings from InfluxDB and compare to baseline.

        Returns a score 0-100 based on how far current avg speed deviates
        from the baseline for this segment/hour/day combination.
        """
        try:
            from traffic_ai.db.influx import query_points
            now = datetime.now(timezone.utc)
            query = f"""
            from(bucket: "traffic_metrics")
              |> range(start: -15m)
              |> filter(fn: (r) => r._measurement == "loop_detector")
              |> filter(fn: (r) => r.segment_id == "{segment_id}")
              |> filter(fn: (r) => r._field == "speed_kmh")
              |> mean()
            """
            points = await query_points(query)
            if not points:
                return 0.0
            current_avg = float(points[0].get("_value", 0))

            # Fetch baseline from PostgreSQL
            if self.db is not None:
                from traffic_ai.models.orm import SpeedBaseline
                result = await self.db.execute(
                    select(SpeedBaseline).where(
                        SpeedBaseline.segment_id == segment_id,
                        SpeedBaseline.hour_of_day == now.hour,
                        SpeedBaseline.day_of_week == now.weekday(),
                    )
                )
                baseline = result.scalar_one_or_none()
                if baseline and baseline.avg_speed_kmh > 0:
                    deviation = abs(current_avg - baseline.avg_speed_kmh) / baseline.avg_speed_kmh
                    return min(deviation * 100, 100.0)
            return 0.0
        except Exception:
            logger.exception("Error in _calc_speed_deviation for %s", segment_id)
            return 0.0

    async def _calc_incident_proximity(self, segment_id: str) -> float:
        """Count recent incidents near the segment from PostgreSQL.

        Returns a score 0-100 based on incident count and severity.
        """
        if self.db is None:
            return 0.0
        try:
            from traffic_ai.models.orm import Incident
            cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            result = await self.db.execute(
                select(func.count(Incident.id), func.coalesce(func.avg(Incident.severity), 1)).where(
                    Incident.segment_id == segment_id,
                    Incident.status == "active",
                    Incident.started_at >= cutoff,
                )
            )
            row = result.one_or_none()
            if row is None:
                return 0.0
            count, avg_severity = row[0], row[1]
            # Scale: 0 incidents = 0, 5+ incidents = 100, weighted by severity
            base = min(count / 5.0, 1.0) * 100
            severity_factor = min(float(avg_severity) / 5.0, 1.0) if avg_severity else 0.5
            return min(base * severity_factor, 100.0)
        except Exception:
            logger.exception("Error in _calc_incident_proximity for %s", segment_id)
            return 0.0

    async def _calc_flow_density(self, segment_id: str) -> float:
        """Use flow/density ratio from sensor data to assess congestion.

        Returns a score 0-100 where higher means more congested.
        """
        try:
            from traffic_ai.db.influx import query_points
            query = f"""
            from(bucket: "traffic_metrics")
              |> range(start: -15m)
              |> filter(fn: (r) => r._measurement == "loop_detector")
              |> filter(fn: (r) => r.segment_id == "{segment_id}")
              |> filter(fn: (r) => r._field == "occupancy_pct")
              |> mean()
            """
            points = await query_points(query)
            if not points:
                return 0.0
            # occupancy_pct directly maps: 0% = free flow, 100% = full congestion
            occupancy = float(points[0].get("_value", 0))
            return min(max(occupancy, 0.0), 100.0)
        except Exception:
            logger.exception("Error in _calc_flow_density for %s", segment_id)
            return 0.0

    async def _calc_weather(self, segment_id: str) -> float:
        """Get latest weather data and compute severity score.

        Returns a score 0-100 based on precipitation, wind, and visibility.
        """
        try:
            from traffic_ai.db.influx import query_points
            query = """
            from(bucket: "traffic_metrics")
              |> range(start: -1h)
              |> filter(fn: (r) => r._measurement == "weather")
              |> last()
            """
            points = await query_points(query)
            if not points:
                return 0.0

            # Gather latest weather values
            values: dict[str, float] = {}
            for p in points:
                field_name = p.get("_field", "")
                value = p.get("_value")
                if value is not None:
                    values[field_name] = float(value)

            score = 0.0
            # Precipitation: 0mm = 0, 10mm+ = 40 pts
            precip = values.get("precipitation_mm", 0)
            score += min(precip / 10.0, 1.0) * 40

            # Wind speed: 0 km/h = 0, 60+ km/h = 30 pts
            wind = values.get("wind_speed_kmh", 0)
            score += min(wind / 60.0, 1.0) * 30

            # Low visibility: 10km+ = 0, <1km = 30 pts
            vis = values.get("visibility_m", 10000)
            if vis < 10000:
                score += (1.0 - min(vis / 10000.0, 1.0)) * 30

            return min(score, 100.0)
        except Exception:
            logger.exception("Error in _calc_weather for %s", segment_id)
            return 0.0

    async def _calc_infrastructure_health(self, segment_id: str) -> float:
        """Query asset condition scores for the segment.

        Returns a score 0-100 where higher means worse infrastructure health (higher risk).
        """
        if self.db is None:
            return 0.0
        try:
            from traffic_ai.models.orm import RoadAsset
            result = await self.db.execute(
                select(func.avg(RoadAsset.condition_score)).where(
                    RoadAsset.segment_id == segment_id,
                    RoadAsset.condition_score.isnot(None),
                )
            )
            avg_score = result.scalar()
            if avg_score is None:
                return 0.0
            # condition_score: 1=excellent, 5=terrible. Map to 0-100.
            return min(max((float(avg_score) - 1) / 4.0 * 100, 0.0), 100.0)
        except Exception:
            logger.exception("Error in _calc_infrastructure_health for %s", segment_id)
            return 0.0

    async def _calc_time_factor(self, segment_id: str) -> float:
        """Score based on time-of-day traffic patterns."""
        hour = datetime.now(timezone.utc).hour
        if 7 <= hour <= 9 or 16 <= hour <= 19:
            return 60.0  # Rush hours
        elif 22 <= hour or hour <= 5:
            return 40.0  # Late night (lower traffic but higher risk per vehicle)
        return 20.0

    async def _calc_historical_baseline(self, segment_id: str) -> float:
        """Compare current hour's readings to historical baselines.

        Returns a score 0-100 based on how unusual current conditions are
        compared to the historical norm.
        """
        try:
            from traffic_ai.db.influx import query_points
            now = datetime.now(timezone.utc)
            # Get current speed
            query = f"""
            from(bucket: "traffic_metrics")
              |> range(start: -15m)
              |> filter(fn: (r) => r._measurement == "loop_detector")
              |> filter(fn: (r) => r.segment_id == "{segment_id}")
              |> filter(fn: (r) => r._field == "speed_kmh")
              |> mean()
            """
            points = await query_points(query)
            if not points:
                return 0.0
            current_speed = float(points[0].get("_value", 0))

            if self.db is not None:
                from traffic_ai.models.orm import SpeedBaseline
                result = await self.db.execute(
                    select(SpeedBaseline).where(
                        SpeedBaseline.segment_id == segment_id,
                        SpeedBaseline.hour_of_day == now.hour,
                        SpeedBaseline.day_of_week == now.weekday(),
                    )
                )
                baseline = result.scalar_one_or_none()
                if baseline and baseline.std_speed_kmh and baseline.std_speed_kmh > 0:
                    z_score = abs(current_speed - baseline.avg_speed_kmh) / baseline.std_speed_kmh
                    # z_score >= 3 => 100, z_score = 0 => 0
                    return min(z_score / 3.0 * 100, 100.0)
            return 0.0
        except Exception:
            logger.exception("Error in _calc_historical_baseline for %s", segment_id)
            return 0.0

    async def explain_with_shap(self, segment_id: str) -> dict[str, Any]:
        """SHAP-style explanation using factor contributions.

        Computes each factor's weighted contribution to the total score,
        providing a meaningful explanation of what drives the risk.
        """
        factors = await self._gather_factors(segment_id)
        fd = factors.as_dict()

        contributions: dict[str, float] = {}
        total = 0.0
        for name, value in fd.items():
            weight = self.weights.get(name, 0.0)
            contribution = value * weight
            contributions[name] = round(contribution, 4)
            total += contribution

        # Normalize to show relative importance
        relative: dict[str, float] = {}
        if total > 0:
            for name, contrib in contributions.items():
                relative[name] = round(contrib / total, 4)
        else:
            relative = {name: 0.0 for name in contributions}

        return {
            "segment_id": segment_id,
            "total_score": round(min(max(total, 0.0), 100.0), 2),
            "factor_contributions": contributions,
            "relative_importance": relative,
            "note": "Factor-based SHAP-style explanation. Full SHAP integration requires trained model artifact.",
        }
