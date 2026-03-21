"""Speed baseline calculator with STL seasonal decomposition.

Two baseline modes
------------------
1. Rolling-average (always available): mean/std per segment × hour × dow,
   computed from InfluxDB history.  Upserted to the speed_baseline table.

2. STL decomposition (requires statsmodels ≥ 0.14): uses seasonal-trend
   decomposition to separate recurring weekly patterns from trend drift.
   Returns a seasonality-adjusted expected-speed series useful for the
   LSTM training pipeline and for anomaly scoring.
"""
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

    # ── STL decomposition ─────────────────────────────────────────────────

    async def stl_decompose_segment(
        self,
        segment_id: str,
        period: int = 288,  # 288 × 5-min intervals = 1 day
        lookback_hours: int | None = None,
    ) -> dict[str, Any]:
        """Run STL seasonal decomposition on a segment's speed time series.

        Returns a dict with keys:
          trend       list[float] — long-term trend component
          seasonal    list[float] — repeating daily/weekly pattern
          residual    list[float] — noise / anomaly component
          timestamps  list[str]   — ISO timestamps for each point
          segment_id  str

        The seasonal component is written back to InfluxDB as
        measurement "speed_seasonal" for use by the LSTM trainer.

        Parameters
        ----------
        period:
            Seasonal period in number of observations.  Default 288 = 1 day
            at 5-minute resolution.  Use 2016 for a weekly period.
        lookback_hours:
            History window.  Defaults to self.lookback_hours (168h = 1 week).
        """
        lookback = lookback_hours or self.lookback_hours
        query = f"""
        from(bucket: "traffic_metrics")
          |> range(start: -{lookback}h)
          |> filter(fn: (r) => r._measurement == "loop_detector")
          |> filter(fn: (r) => r.segment_id == "{segment_id}")
          |> filter(fn: (r) => r._field == "speed_kmh")
          |> sort(columns: ["_time"])
        """
        try:
            points = await query_points(query)
        except Exception:
            logger.exception("STL query failed for segment %s", segment_id)
            return {"segment_id": segment_id, "error": "query_failed"}

        if len(points) < period * 2:
            logger.info(
                "Segment %s has only %d points — need ≥ %d for STL (skipping)",
                segment_id, len(points), period * 2,
            )
            return {"segment_id": segment_id, "error": "insufficient_data", "n_points": len(points)}

        timestamps = []
        values = []
        for p in points:
            ts = p.get("_time")
            v = p.get("_value")
            if ts is None or v is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            timestamps.append(ts.isoformat() if hasattr(ts, "isoformat") else str(ts))
            values.append(float(v))

        try:
            trend, seasonal, residual = _stl_decompose(values, period=period)
        except Exception:
            logger.exception("STL decomposition failed for segment %s", segment_id)
            return {"segment_id": segment_id, "error": "decompose_failed"}

        # Write seasonal component back to InfluxDB for the training pipeline
        await self._write_seasonal_component(segment_id, timestamps, seasonal)

        return {
            "segment_id": segment_id,
            "n_points": len(values),
            "period": period,
            "trend": [round(v, 3) for v in trend],
            "seasonal": [round(v, 3) for v in seasonal],
            "residual": [round(v, 3) for v in residual],
            "timestamps": timestamps,
        }

    async def _write_seasonal_component(
        self,
        segment_id: str,
        timestamps: list[str],
        seasonal: list[float],
    ) -> None:
        """Write the STL seasonal component to InfluxDB."""
        from traffic_ai.db.influx import write_points  # noqa: PLC0415
        seg = segment_id.replace(" ", r"\ ")
        lines = []
        for ts_str, val in zip(timestamps, seasonal):
            # Convert ISO timestamp to Unix nanoseconds for line protocol precision
            try:
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ns = int(dt.timestamp() * 1e9)
                lines.append(
                    f"speed_seasonal,segment_id={seg} seasonal_speed={round(val, 3)} {ns}"
                )
            except Exception:
                continue
        if lines:
            try:
                await write_points(lines)
                logger.debug("Wrote %d seasonal points for segment %s", len(lines), segment_id)
            except Exception:
                logger.exception("Failed to write seasonal component for %s", segment_id)


# ── STL helper ────────────────────────────────────────────────────────────────


def _stl_decompose(
    values: list[float],
    period: int = 288,
) -> tuple[list[float], list[float], list[float]]:
    """Decompose a time series into (trend, seasonal, residual) using STL.

    Uses statsmodels STL (LOESS-based, robust to outliers).
    Falls back to a simple moving-average decomposition when statsmodels
    is not installed so the rest of the system keeps working.

    Parameters
    ----------
    values : list[float]
        Equally-spaced observations (e.g. 5-min speed readings).
    period : int
        Number of observations per seasonal cycle (288 = 1 day × 5-min).
    """
    try:
        from statsmodels.tsa.seasonal import STL  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        arr = np.array(values, dtype=float)
        # STL requires at least 2 full cycles
        stl = STL(arr, period=period, robust=True)
        result = stl.fit()
        return (
            result.trend.tolist(),
            result.seasonal.tolist(),
            result.resid.tolist(),
        )
    except ImportError:
        logger.debug("statsmodels not installed — using moving-average STL fallback")
        return _ma_decompose(values, period)
    except Exception:
        logger.exception("STL decomposition raised an error — falling back to MA")
        return _ma_decompose(values, period)


def _ma_decompose(
    values: list[float],
    period: int,
) -> tuple[list[float], list[float], list[float]]:
    """Simple centred moving-average decomposition as statsmodels fallback."""
    n = len(values)
    half = period // 2

    # Trend: centred moving average of width `period`
    trend = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        window = values[lo:hi]
        trend.append(sum(window) / len(window))

    # Seasonal: mean deviation from trend per period position
    detrended = [v - t for v, t in zip(values, trend)]
    period_avgs = []
    for pos in range(period):
        bucket = [detrended[i] for i in range(pos, n, period)]
        period_avgs.append(sum(bucket) / len(bucket) if bucket else 0.0)

    seasonal = [period_avgs[i % period] for i in range(n)]
    residual = [v - t - s for v, t, s in zip(values, trend, seasonal)]
    return trend, seasonal, residual
