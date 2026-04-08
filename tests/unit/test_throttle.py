"""Tests for the throttle logic bug fix (OR vs AND)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from traffic_ai.config import PROFILES, RuntimeResourceManager


class TestThrottleLogic:
    """Verify the bug-fix: throttle triggers on CPU OR memory exceeding threshold."""

    def _make_manager(self, profile_name: str = "balanced") -> RuntimeResourceManager:
        return RuntimeResourceManager(profile=PROFILES[profile_name])

    def test_no_throttle_when_both_below(self):
        mgr = self._make_manager()
        with patch.object(mgr, "cpu_percent", return_value=50.0), \
             patch.object(mgr, "memory_percent", return_value=50.0):
            assert mgr.should_throttle() is False

    def test_throttle_when_cpu_high_mem_low(self):
        """Bug-fix test: CPU alone exceeding threshold MUST trigger throttle."""
        mgr = self._make_manager()
        with patch.object(mgr, "cpu_percent", return_value=95.0), \
             patch.object(mgr, "memory_percent", return_value=50.0):
            assert mgr.should_throttle() is True

    def test_throttle_when_mem_high_cpu_low(self):
        """Bug-fix test: Memory alone exceeding threshold MUST trigger throttle."""
        mgr = self._make_manager()
        with patch.object(mgr, "cpu_percent", return_value=50.0), \
             patch.object(mgr, "memory_percent", return_value=95.0):
            assert mgr.should_throttle() is True

    def test_throttle_when_both_high(self):
        mgr = self._make_manager()
        with patch.object(mgr, "cpu_percent", return_value=95.0), \
             patch.object(mgr, "memory_percent", return_value=95.0):
            assert mgr.should_throttle() is True

    def test_available_concurrency_normal(self):
        mgr = self._make_manager("prosumer")
        with patch.object(mgr, "cpu_percent", return_value=50.0), \
             patch.object(mgr, "memory_percent", return_value=50.0):
            assert mgr.available_concurrency() == 12

    def test_available_concurrency_throttled(self):
        mgr = self._make_manager("prosumer")
        with patch.object(mgr, "cpu_percent", return_value=95.0), \
             patch.object(mgr, "memory_percent", return_value=50.0):
            assert mgr.available_concurrency() == 6

    @pytest.mark.parametrize("profile_name", ["lite", "prosumer", "balanced", "full", "benchmark"])
    def test_throttle_respects_profile_thresholds(self, profile_name: str):
        mgr = self._make_manager(profile_name)
        threshold = PROFILES[profile_name].throttle_cpu_pct
        with patch.object(mgr, "cpu_percent", return_value=threshold + 1), \
             patch.object(mgr, "memory_percent", return_value=0.0):
            assert mgr.should_throttle() is True
