"""Weather ingestors -- NOAA (US) and AEMET (Spain)."""
from __future__ import annotations
import logging
from typing import Any
import aiohttp
from traffic_ai.config import settings
from traffic_ai.db.influx import write_points
from traffic_ai.ingestors.base import BaseIngestor

logger = logging.getLogger(__name__)


class NOAAWeatherIngestor(BaseIngestor):
    """Ingests weather observations from the NOAA Weather API (api.weather.gov)."""
    NOAA_BASE_URL = "https://api.weather.gov"

    def __init__(self, station_ids: list[str] | None = None) -> None:
        super().__init__(name="noaa_weather")
        self.station_ids: list[str] = station_ids or []

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        headers = {"User-Agent": "TrafficAI/1.0", "Accept": "application/geo+json"}
        async with aiohttp.ClientSession(headers=headers) as session:
            for station_id in self.station_ids:
                try:
                    url = f"{self.NOAA_BASE_URL}/stations/{station_id}/observations/latest"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()
                        props = data.get("properties", {})
                        temp_c = props.get("temperature", {}).get("value")
                        humidity = props.get("relativeHumidity", {}).get("value")
                        wind_speed = props.get("windSpeed", {}).get("value")
                        precip = props.get("precipitationLastHour", {}).get("value", 0)
                        visibility = props.get("visibility", {}).get("value")
                        obs = {"station_id": station_id, "temperature_c": temp_c,
                               "humidity_pct": humidity, "wind_speed_kmh": wind_speed,
                               "precipitation_mm": precip or 0, "visibility_m": visibility}
                        results.append(obs)
                        fields = []
                        if temp_c is not None: fields.append(f"temperature_c={temp_c}")
                        if humidity is not None: fields.append(f"humidity_pct={humidity}")
                        if wind_speed is not None: fields.append(f"wind_speed_kmh={wind_speed}")
                        fields.append(f"precipitation_mm={precip or 0}")
                        if visibility is not None: fields.append(f"visibility_m={visibility}")
                        if fields:
                            line = f"weather,station_id={station_id},source=noaa {','.join(fields)}"
                            await write_points(line)
                except Exception:
                    self.logger.exception("Error polling NOAA station %s", station_id)
        return results


class AEMETWeatherIngestor(BaseIngestor):
    """Ingests weather observations from the AEMET OpenData API (Spain)."""
    AEMET_BASE_URL = "https://opendata.aemet.es/opendata/api"

    def __init__(self, station_ids: list[str] | None = None) -> None:
        super().__init__(name="aemet_weather")
        self.station_ids: list[str] = station_ids or []
        self.api_key: str = settings.aemet_api_key

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        results: list[dict[str, Any]] = []
        headers = {"api_key": self.api_key, "Accept": "application/json"}
        async with aiohttp.ClientSession(headers=headers) as session:
            for station_id in self.station_ids:
                try:
                    url = f"{self.AEMET_BASE_URL}/observacion/convencional/datos/estacion/{station_id}"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status != 200:
                            continue
                        meta = await resp.json()
                        data_url = meta.get("datos")
                        if not data_url:
                            continue
                    async with session.get(data_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status != 200:
                            continue
                        observations = await resp.json()
                        if not observations:
                            continue
                        latest = observations[-1]
                        temp_c = latest.get("ta")
                        humidity = latest.get("hr")
                        wind_speed = latest.get("vv")
                        precip = latest.get("prec", 0)
                        visibility = latest.get("vis")
                        obs = {"station_id": station_id, "temperature_c": temp_c,
                               "humidity_pct": humidity, "wind_speed_kmh": wind_speed,
                               "precipitation_mm": precip or 0, "visibility_m": visibility}
                        results.append(obs)
                        fields = []
                        if temp_c is not None: fields.append(f"temperature_c={temp_c}")
                        if humidity is not None: fields.append(f"humidity_pct={humidity}")
                        if wind_speed is not None: fields.append(f"wind_speed_kmh={wind_speed}")
                        fields.append(f"precipitation_mm={precip or 0}")
                        if visibility is not None: fields.append(f"visibility_m={visibility}")
                        if fields:
                            line = f"weather,station_id={station_id},source=aemet {','.join(fields)}"
                            await write_points(line)
                except Exception:
                    self.logger.exception("Error polling AEMET station %s", station_id)
        return results


class CombinedWeatherIngestor(BaseIngestor):
    """Aggregates NOAA and AEMET ingestors into a single interface."""
    def __init__(self, noaa_stations: list[str] | None = None, aemet_stations: list[str] | None = None) -> None:
        super().__init__(name="weather")
        self.noaa = NOAAWeatherIngestor(station_ids=noaa_stations)
        self.aemet = AEMETWeatherIngestor(station_ids=aemet_stations)

    async def start(self) -> None:
        self._running = True
        await self.noaa.start()
        await self.aemet.start()

    async def stop(self) -> None:
        self._running = False
        await self.noaa.stop()
        await self.aemet.stop()

    async def poll(self) -> list[dict[str, Any]]:
        return await self.noaa.poll() + await self.aemet.poll()
