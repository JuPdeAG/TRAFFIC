"""Unit tests for the baseline calculator."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from traffic_ai.analytics.baseline import BaselineCalculator


class TestBaselineCalculator:
    def test_init_defaults(self):
        calc = BaselineCalculator()
        assert calc.lookback_hours == 168
        assert calc.db is None

    def test_init_custom_lookback(self):
        calc = BaselineCalculator(lookback_hours=48)
        assert calc.lookback_hours == 48

    @pytest.mark.asyncio
    async def test_recalculate_all_returns_zero_without_db(self):
        calc = BaselineCalculator(db=None)
        result = await calc.recalculate_all()
        assert result == 0

    @pytest.mark.asyncio
    async def test_recalculate_segment_returns_empty_on_query_failure(self):
        calc = BaselineCalculator()
        with patch("traffic_ai.analytics.baseline.query_points", side_effect=RuntimeError("influx down")):
            result = await calc.recalculate_segment("seg-fail")
        assert result == []

    @pytest.mark.asyncio
    async def test_recalculate_segment_computes_correct_stats(self):
        """Given known speed values, verify avg and std are computed correctly."""
        calc = BaselineCalculator()

        from datetime import datetime, timezone
        speeds = [60.0, 80.0, 70.0, 90.0, 50.0]  # avg=70, std≈15.81
        fake_points = [
            {"_time": datetime(2025, 3, 19, 8, 0, tzinfo=timezone.utc), "_value": v}
            for v in speeds
        ]

        with patch("traffic_ai.analytics.baseline.query_points", new_callable=AsyncMock, return_value=fake_points):
            result = await calc.recalculate_segment("seg-001", tz_name="UTC")

        assert len(result) == 1  # all same hour/dow bucket
        bucket = result[0]
        assert bucket["avg_speed_kmh"] == pytest.approx(70.0, abs=0.01)
        assert bucket["std_speed_kmh"] == pytest.approx(15.81, abs=0.1)
        assert bucket["sample_count"] == 5

    @pytest.mark.asyncio
    async def test_recalculate_segment_skips_none_values(self):
        calc = BaselineCalculator()

        from datetime import datetime, timezone
        fake_points = [
            {"_time": datetime(2025, 3, 19, 9, 0, tzinfo=timezone.utc), "_value": 60.0},
            {"_time": None, "_value": 70.0},   # missing timestamp — skip
            {"_time": datetime(2025, 3, 19, 9, 5, tzinfo=timezone.utc), "_value": None},  # missing value — skip
        ]

        with patch("traffic_ai.analytics.baseline.query_points", new_callable=AsyncMock, return_value=fake_points):
            result = await calc.recalculate_segment("seg-002")

        # Only one valid point — sample_count = 1, std = 0
        assert result[0]["sample_count"] == 1
        assert result[0]["std_speed_kmh"] == 0.0
