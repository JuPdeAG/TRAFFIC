"""Unit tests for the risk scoring engine."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from traffic_ai.analytics.risk_scorer import DEFAULT_WEIGHTS, RiskFactors, RiskScoringEngine


class TestRiskFactors:
    def test_as_dict_has_all_keys(self):
        f = RiskFactors()
        d = f.as_dict()
        assert set(d.keys()) == set(DEFAULT_WEIGHTS.keys())

    def test_default_values_are_zero(self):
        f = RiskFactors()
        assert all(v == 0.0 for v in f.as_dict().values())


class TestWeightedSum:
    def test_all_zero_factors_gives_zero(self):
        engine = RiskScoringEngine()
        assert engine._weighted_sum(RiskFactors()) == 0.0

    def test_weights_sum_to_one(self):
        total = sum(DEFAULT_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_max_factors_gives_100(self):
        engine = RiskScoringEngine()
        factors = RiskFactors(
            speed_deviation=100, incident_proximity=100, flow_density=100,
            historical_baseline=100, infrastructure_health=100,
            time_day_pattern=100, weather=100,
        )
        assert engine._weighted_sum(factors) == pytest.approx(100.0)


class TestScoreToLevel:
    @pytest.mark.parametrize("score,expected", [
        (0,   "low"),
        (24,  "low"),
        (25,  "medium"),
        (49,  "medium"),
        (50,  "high"),
        (74,  "high"),
        (75,  "critical"),
        (100, "critical"),
    ])
    def test_boundaries(self, score, expected):
        assert RiskScoringEngine.score_to_level(score) == expected


class TestComputeWithExplanation:
    @pytest.mark.asyncio
    async def test_returns_required_keys(self):
        engine = RiskScoringEngine()
        # Mock all factor calculations to return 50.0
        with patch.object(engine, "_gather_factors", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = RiskFactors(
                speed_deviation=50, incident_proximity=50, flow_density=50,
                historical_baseline=50, infrastructure_health=50,
                time_day_pattern=50, weather=50,
            )
            result = await engine.compute_with_explanation("seg-001")

        assert "segment_id" in result
        assert "score" in result
        assert "level" in result
        assert "factors" in result
        assert "computed_at" in result
        assert result["segment_id"] == "seg-001"
        assert 0 <= result["score"] <= 100

    @pytest.mark.asyncio
    async def test_score_clamped_between_0_and_100(self):
        engine = RiskScoringEngine(weights={k: 1.0 for k in DEFAULT_WEIGHTS})
        with patch.object(engine, "_gather_factors", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = RiskFactors(
                speed_deviation=200, incident_proximity=200, flow_density=200,
                historical_baseline=200, infrastructure_health=200,
                time_day_pattern=200, weather=200,
            )
            result = await engine.compute_with_explanation("seg-overflow")
        assert result["score"] <= 100.0

    @pytest.mark.asyncio
    async def test_factor_exception_returns_zero_for_that_factor(self):
        engine = RiskScoringEngine()
        # Make one factor raise — engine should silently return 0 for it
        with patch.object(engine, "_calc_speed_deviation", side_effect=RuntimeError("boom")):
            with patch.object(engine, "_calc_incident_proximity", new_callable=AsyncMock, return_value=0.0):
                with patch.object(engine, "_calc_flow_density", new_callable=AsyncMock, return_value=0.0):
                    with patch.object(engine, "_calc_time_factor", new_callable=AsyncMock, return_value=0.0):
                        with patch.object(engine, "_calc_historical_baseline", new_callable=AsyncMock, return_value=0.0):
                            with patch.object(engine, "_calc_infrastructure_health", new_callable=AsyncMock, return_value=0.0):
                                with patch.object(engine, "_calc_weather", new_callable=AsyncMock, return_value=0.0):
                                    result = await engine.compute_with_explanation("seg-error")
        assert result["score"] == 0.0  # all factors 0


class TestTimeFactorScore:
    @pytest.mark.asyncio
    async def test_rush_hour_score(self):
        engine = RiskScoringEngine()
        with patch("traffic_ai.analytics.risk_scorer.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=8)
            score = await engine._calc_time_factor("any")
        assert score == 60.0

    @pytest.mark.asyncio
    async def test_off_peak_score(self):
        engine = RiskScoringEngine()
        with patch("traffic_ai.analytics.risk_scorer.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(hour=14)
            score = await engine._calc_time_factor("any")
        assert score == 20.0


class TestShapExplain:
    @pytest.mark.asyncio
    async def test_relative_importance_sums_to_one(self):
        engine = RiskScoringEngine()
        with patch.object(engine, "_gather_factors", new_callable=AsyncMock) as mock_gather:
            mock_gather.return_value = RiskFactors(
                speed_deviation=80, incident_proximity=60, flow_density=40,
                historical_baseline=30, infrastructure_health=20,
                time_day_pattern=50, weather=10,
            )
            result = await engine.explain_with_shap("seg-001")

        rel = result["relative_importance"]
        total = sum(rel.values())
        assert abs(total - 1.0) < 1e-6
        assert "factor_contributions" in result
        assert "total_score" in result
