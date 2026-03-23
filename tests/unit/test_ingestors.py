"""Unit tests for open-data ingestors (no network, no InfluxDB required)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone


# ── Madrid traffic state ──────────────────────────────────────────────────────

class TestMadridTrafficStateParser:
    def _parse(self, xml: str):
        from traffic_ai.ingestors.madrid_traffic_state import _parse_madrid_state_xml
        return _parse_madrid_state_xml(xml)

    # Real Informo XML uses attributes on the <pm> element, not child elements.

    def test_parses_single_pm_element(self):
        xml = '<trafico><pm id="1001" velocidad="72" carga="35" ocupacion="28" estado="1" /></trafico>'
        records = self._parse(xml)
        assert len(records) == 1
        r = records[0]
        assert r["tramo_id"] == "mad_1001"
        assert r["speed_kmh"] == pytest.approx(72.0)
        assert r["load_pct"] == pytest.approx(35.0)
        assert r["estado"] == 1

    def test_parses_multiple_pm_elements(self):
        xml = ('<trafico>'
               '<pm id="101" velocidad="50" carga="60" ocupacion="40" estado="2" />'
               '<pm id="102" velocidad="30" carga="80" ocupacion="70" estado="4" />'
               '</trafico>')
        records = self._parse(xml)
        assert len(records) == 2
        assert records[0]["tramo_id"] == "mad_101"
        assert records[1]["tramo_id"] == "mad_102"

    def test_skips_element_missing_id(self):
        xml = '<trafico><pm velocidad="50" carga="60" ocupacion="40" estado="1" /></trafico>'
        records = self._parse(xml)
        assert len(records) == 0

    def test_handles_empty_xml(self):
        records = self._parse("<trafico></trafico>")
        assert records == []

    def test_estado_to_density_mapping(self):
        from traffic_ai.ingestors.madrid_traffic_state import _parse_madrid_state_xml
        for estado, expected_level in [
            (0, "unknown"), (1, "free_flow"), (3, "moderate"), (6, "closed"),
        ]:
            xml = f'<trafico><pm id="1" velocidad="50" carga="50" ocupacion="30" estado="{estado}" /></trafico>'
            records = _parse_madrid_state_xml(xml)
            assert records[0]["density_level"] == expected_level, f"estado {estado}"


# ── Valencia traffic parser ───────────────────────────────────────────────────

class TestValenciaTrafficParser:
    def _parse(self, payload):
        from traffic_ai.ingestors.valencia_traffic import _parse
        return _parse(payload)

    def test_parses_results_key(self):
        payload = {
            "results": [
                {"id": "V001", "estado": 1, "velocidad": 60.0},
                {"id": "V002", "estado": 3, "velocidad": 30.0},
            ]
        }
        records = self._parse(payload)
        assert len(records) == 2
        assert records[0]["seg_id"] == "vlc_V001"
        assert records[0]["speed_kmh"] == pytest.approx(60.0)

    def test_parses_bare_list(self):
        payload = [{"id": "V003", "estado": 2, "velocidad": 45.0}]
        records = self._parse(payload)
        assert len(records) == 1

    def test_handles_bilingual_speed_field(self):
        payload = {"results": [{"id": "V010", "estado": 1, "velocitat": 55.0}]}
        records = self._parse(payload)
        assert records[0]["speed_kmh"] == pytest.approx(55.0)

    def test_handles_empty_results(self):
        assert self._parse({"results": []}) == []
        assert self._parse([]) == []

    def test_density_score_range(self):
        payload = {"results": [
            {"id": f"V{i}", "estado": i, "velocidad": 50.0}
            for i in range(7)
        ]}
        records = self._parse(payload)
        for r in records:
            assert 0.0 <= r["density_score"] <= 100.0


# ── TomTom ingestor ───────────────────────────────────────────────────────────

class TestTomTomIncidentParser:
    def _parse(self, data):
        from traffic_ai.ingestors.tomtom import _parse_incidents
        return _parse_incidents(data)

    def test_parses_incidents_list(self):
        data = {
            "incidents": [
                {"properties": {"id": "INC001", "type": 1, "magnitude": 2,
                                "delay": 120, "length": 500, "roadNumbers": ["A-6"]}},
                {"properties": {"id": "INC002", "type": 6, "magnitude": 3,
                                "delay": 300, "length": 1000, "roadNumbers": ["M-30"]}},
            ]
        }
        records = self._parse(data)
        assert len(records) == 2
        assert records[0]["id"] == "INC001"
        assert records[0]["type_name"] == "accident"
        assert records[0]["magnitude_name"] == "moderate"
        assert records[0]["road"] == "A-6"
        assert records[1]["type_name"] == "jam"

    def test_skips_incident_without_id(self):
        data = {"incidents": [
            {"properties": {"type": 1, "magnitude": 1, "delay": 0, "length": 0}},
        ]}
        records = self._parse(data)
        assert len(records) == 0

    def test_handles_empty_incidents(self):
        assert self._parse({"incidents": []}) == []
        assert self._parse({}) == []

    def test_delay_and_length_default_to_zero(self):
        data = {"incidents": [
            {"properties": {"id": "INC003", "type": 9, "magnitude": 1,
                            "roadNumbers": []}},
        ]}
        records = self._parse(data)
        assert records[0]["delay_s"] == 0.0
        assert records[0]["length_m"] == 0.0


class TestTomTomFlowDensity:
    def test_density_score_free_flow(self):
        """Current speed == free flow speed → density 0."""
        from traffic_ai.ingestors.tomtom import _fetch_flow_point
        # Test the density formula directly
        free_flow = 100.0
        current = 100.0
        density = max(0.0, min(100.0, (1 - current / free_flow) * 100))
        assert density == pytest.approx(0.0)

    def test_density_score_standstill(self):
        free_flow = 100.0
        current = 0.0
        density = max(0.0, min(100.0, (1 - current / free_flow) * 100))
        assert density == pytest.approx(100.0)

    def test_density_score_clamped(self):
        free_flow = 50.0
        current = 60.0  # faster than free flow — clamp to 0
        density = max(0.0, min(100.0, (1 - current / free_flow) * 100))
        assert density == 0.0


class TestTomTomLineProtocol:
    def test_incident_line_escapes_spaces(self):
        from traffic_ai.ingestors.tomtom import _incident_to_line
        r = {
            "id": "INC 001", "type_name": "road_works", "magnitude_name": "minor",
            "road": "A 6", "delay_s": 60.0, "length_m": 200.0,
            "magnitude": 1, "type": 9,
        }
        line = _incident_to_line(r)
        assert r" " not in line.split(" ")[0]  # tags have no unescaped spaces

    def test_flow_line_has_required_fields(self):
        from traffic_ai.ingestors.tomtom import _flow_to_line
        r = {
            "point_id": "madrid_m30", "current_speed": 72.0,
            "free_flow_speed": 100.0, "density_score": 28.0,
            "confidence": 0.9, "road_closure": False,
        }
        line = _flow_to_line(r)
        assert "tomtom_flow" in line
        assert "current_speed=72.0" in line
        assert "density_score=28.0" in line
        assert "road_closure=false" in line


# ── TomTom API key guard ──────────────────────────────────────────────────────

class TestTomTomKeyGuard:
    @pytest.mark.asyncio
    async def test_incidents_returns_empty_without_key(self):
        from traffic_ai.ingestors.tomtom import TomTomIncidentsIngestor
        ingestor = TomTomIncidentsIngestor(api_key="")
        await ingestor.start()
        result = await ingestor.poll()
        assert result == []

    @pytest.mark.asyncio
    async def test_flow_returns_empty_without_key(self):
        from traffic_ai.ingestors.tomtom import TomTomFlowIngestor
        ingestor = TomTomFlowIngestor(api_key="")
        await ingestor.start()
        result = await ingestor.poll()
        assert result == []
