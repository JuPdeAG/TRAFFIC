"""Unit tests for the alert engine."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def mock_db():
    """Return a mock AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def _make_execute_result(existing_incident=None):
    """Return a mock execute result that yields the given incident (or None)."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_incident
    return result


class TestEvaluateAndAlert:
    @pytest.mark.asyncio
    async def test_creates_critical_alert_above_threshold(self, mock_db):
        from traffic_ai.analytics.alert_engine import evaluate_and_alert

        mock_db.execute = AsyncMock(return_value=_make_execute_result(None))
        actions = await evaluate_and_alert(mock_db, "seg-001", score=80.0, pilot="test")

        assert any("created:critical" in a for a in actions)
        mock_db.add.assert_called()

    @pytest.mark.asyncio
    async def test_creates_high_alert_above_threshold(self, mock_db):
        from traffic_ai.analytics.alert_engine import evaluate_and_alert

        mock_db.execute = AsyncMock(return_value=_make_execute_result(None))
        actions = await evaluate_and_alert(mock_db, "seg-001", score=55.0, pilot="test")

        # score 55 >= high(50) but < critical(75) — only high alert created
        assert any("created:high" in a for a in actions)
        assert not any("created:critical" in a for a in actions)

    @pytest.mark.asyncio
    async def test_no_alert_below_threshold(self, mock_db):
        from traffic_ai.analytics.alert_engine import evaluate_and_alert

        mock_db.execute = AsyncMock(return_value=_make_execute_result(None))
        actions = await evaluate_and_alert(mock_db, "seg-001", score=30.0, pilot="test")

        assert actions == []
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_duplicate_alert_when_existing_active(self, mock_db):
        from traffic_ai.analytics.alert_engine import evaluate_and_alert
        from traffic_ai.models.orm import Incident

        existing = MagicMock(spec=Incident)
        existing.status = "active"
        mock_db.execute = AsyncMock(return_value=_make_execute_result(existing))

        actions = await evaluate_and_alert(mock_db, "seg-001", score=80.0)

        assert not any("created" in a for a in actions)
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolves_alert_when_score_drops(self, mock_db):
        from traffic_ai.analytics.alert_engine import evaluate_and_alert
        from traffic_ai.models.orm import Incident

        existing = MagicMock(spec=Incident)
        existing.status = "active"

        # First call returns existing for critical, None for high
        call_count = 0
        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            # Return existing incident on first query (critical), None on second (high)
            result.scalar_one_or_none.return_value = existing if call_count == 1 else None
            return result

        mock_db.execute = side_effect

        # Score dropped below clear threshold (70) for critical
        actions = await evaluate_and_alert(mock_db, "seg-001", score=68.0)

        assert any("resolved:critical" in a for a in actions)
        assert existing.status == "resolved"


class TestLevelToSeverity:
    def test_known_levels(self):
        from traffic_ai.analytics.alert_engine import _level_to_severity
        assert _level_to_severity("critical") == 5
        assert _level_to_severity("high") == 4
        assert _level_to_severity("medium") == 3
        assert _level_to_severity("low") == 2

    def test_unknown_level_returns_default(self):
        from traffic_ai.analytics.alert_engine import _level_to_severity
        assert _level_to_severity("unknown") == 3
