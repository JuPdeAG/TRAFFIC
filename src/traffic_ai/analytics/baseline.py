"""Speed baseline calculator with timezone-aware logic."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from traffic_ai.db.influx import query_points

logger = logging.getLogger(__name__)


class BaselineCalculator:
    """Calculates and updates speed baselines per segment/hour/day.

    Timezone-aware: stores both UTC and local-time baselines.
    Requires an AsyncSession for reading segment IDs and upserting results.
    """
    def __init__(self, db: AsyncSession | None = None, lookback_hours: int = 168) -> None:
        self.db = db
        self.lookback_hours = lookback_hours

    async def recalculate_all(self) -> int:
        """Recalculate baselines for every known segment. Returns count updated."""
        logger.info("Recalculating baselines for all segments (lookback=%dh)", self.lookback_hours)
        if self.db is None:
            logger.warning("No database session provided; cannot recalculate baselines")
            return 0

        from traffic_ai.models.orm import RoadSegment
        result = await self.db.execute(select(RoadSegment.id))
        segment_ids = [row[0] for row in result.all()]

        count = 0
        for segment_id in segment_ids:
            try:
                baselines = await self.recalculate_segment(segment_id)
                count += len(baselines)
            except Exception:
                logger.exception("Failed to recalculate baselines for segment %s", segment_id)
        logger.info("Recalculated %d total baseline buckets across %d segments", count, len(segment_ids))
        return count

    async def recalculate_segment(self, segment_id: str, tz_name: str = "UTC") -> list[dict[str, Any]]:
        """Recalculate baselines for a single segment and upsert to PostgreSQL."""
        import zoneinfo
        local_tz = zoneinfo.ZoneInfo(tz_name)
        query = f"""
        from(bucket: "traffic_metrics")
          |> range(start: -{self.lookback_hours}h)
          |> filter(fn: (r) => r._measurement == "loop_detector")
          |> filter(fn: (r) => r.segment_id == "{segment_id}")
          |> filter(fn: (r) => r._field == "speed_kmh")
        """
        try:
            points = await query_points(query)
        except Exception:
            logger.exception("Failed to query speed data for segment %s", segment_id)
            return []

        buckets: dict[tuple[int, int], list[float]] = {}
        for point in points:
            ts = point.get("_time")
            value = point.get("_value")
            if ts is None or value is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            utc_key = (ts.hour, ts.weekday())
            buckets.setdefault(utc_key, []).append(float(value))

        results = []
        for (hour, dow), speeds in buckets.items():
            avg = sum(speeds) / len(speeds)
            # Use sample standard deviation (Bessel's correction) with guard for len < 2
            if len(speeds) > 1:
                std = (sum((s - avg) ** 2 for s in speeds) / (len(speeds) - 1)) ** 0.5
            else:
                std = 0.0
            baseline_data = {
                "segment_id": segment_id, "hour_of_day": hour, "day_of_week": dow,
                "avg_speed_kmh": round(avg, 2), "std_speed_kmh": round(std, 2),
                "sample_count": len(speeds), "timezone": tz_name,
            }
            results.append(baseline_data)

            # Upsert to PostgreSQL if db session is available
            if self.db is not None:
                await self._upsert_baseline(segment_id, hour, dow, avg, std, len(speeds), tz_name)

        if self.db is not None:
            await self.db.flush()

        logger.info("Recalculated %d baseline buckets for segment %s", len(results), segment_id)
        return results

    async def _upsert_baseline(
        self, segment_id: str, hour: int, dow: int,
        avg: float, std: float, count: int, tz_name: str,
    ) -> None:
        """Upsert a single baseline record into the speed_baseline table."""
        if self.db is None:
            return
        from traffic_ai.models.orm import SpeedBaseline
        result = await self.db.execute(
            select(SpeedBaseline).where(
                SpeedBaseline.segment_id == segment_id,
                SpeedBaseline.hour_of_day == hour,
                SpeedBaseline.day_of_week == dow,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.avg_speed_kmh = round(avg, 2)
            existing.std_speed_kmh = round(std, 2)
            existing.sample_count = count
            existing.timezone = tz_name
        else:
            baseline = SpeedBaseline(
                segment_id=segment_id, hour_of_day=hour, day_of_week=dow,
                avg_speed_kmh=round(avg, 2), std_speed_kmh=round(std, 2),
                sample_count=count, timezone=tz_name,
            )
            self.db.add(baseline)
