"""Tests for configuration and profile loading."""
from __future__ import annotations

import pytest

from traffic_ai.config import PROFILES, ProfileConfig, Settings


class TestProfiles:
    """Verify all 5 profiles are correctly defined."""
    def test_all_profiles_exist(self):
        expected = {"lite", "prosumer", "balanced", "full", "benchmark"}
        assert set(PROFILES.keys()) == expected

    @pytest.mark.parametrize("name", ["lite", "prosumer", "balanced", "full", "benchmark"])
    def test_profile_is_valid(self, name: str):
        profile = PROFILES[name]
        assert isinstance(profile, ProfileConfig)
        assert profile.name == name
        assert profile.max_cameras > 0
        assert profile.celery_concurrency > 0
        assert 0 < profile.throttle_cpu_pct <= 100
        assert 0 < profile.throttle_mem_pct <= 100

    def test_lite_has_lowest_resources(self):
        lite = PROFILES["lite"]
        for name, profile in PROFILES.items():
            if name == "lite":
                continue
            assert lite.max_cameras <= profile.max_cameras
            assert lite.celery_concurrency <= profile.celery_concurrency

    def test_benchmark_has_highest_cameras(self):
        benchmark = PROFILES["benchmark"]
        for profile in PROFILES.values():
            assert benchmark.max_cameras >= profile.max_cameras


class TestSettings:
    """Test Settings class."""
    def test_default_settings(self):
        s = Settings(_env_file=None)
        assert s.profile == "balanced"
        assert s.environment == "development"

    def test_custom_profile(self):
        s = Settings(profile="prosumer", _env_file=None)
        assert s.profile == "prosumer"
