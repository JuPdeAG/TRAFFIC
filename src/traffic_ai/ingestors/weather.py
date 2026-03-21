"""Weather ingestors -- NOAA (US), AEMET (Spain), and Open-Meteo (global)."""
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


_DEFAULT_OPEN_METEO_LOCATIONS: list[dict] = [{"lat": 40.4168, "lon": -3.7038, "name": "Madrid"}]

# WMO weather codes that indicate fog
_FOG_WEATHER_CODES: frozenset[int] = frozenset({45, 48})

_OPEN_METEO_FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,"
    "visibility,weather_code,cloud_cover"
    "&timezone=auto"
)


class OpenMeteoIngestor(BaseIngestor):
    """Ingests live weather forecasts from the Open-Meteo API (no API key required)."""

    def __init__(self, locations: list[dict] | None = None) -> None:
        super().__init__(name="open_meteo_weather")
        configured = getattr(settings, "open_meteo_locations", None)
        self.locations: list[dict] = locations or configured or _DEFAULT_OPEN_METEO_LOCATIONS

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        async with aiohttp.ClientSession() as session:
            for loc in self.locations:
                lat = loc.get("lat")
                lon = loc.get("lon")
                name = loc.get("name", f"{lat},{lon}")
                url = _OPEN_METEO_FORECAST_URL.format(lat=lat, lon=lon)
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status != 200:
                            self.logger.warning(
                                "Open-Meteo returned HTTP %d for location %s", resp.status, name
                            )
                            continue
                        data = await resp.json()
                except Exception:
                    self.logger.warning("Open-Meteo request failed for location %s", name)
                    continue

                try:
                    current = data.get("current", {})
                    temperature_c = current.get("temperature_2m")
                    wind_speed_kmh = current.get("wind_speed_10m")
                    precipitation_mm = current.get("precipitation", 0.0)
                    visibility_m = current.get("visibility")
                    weather_code = current.get("weather_code", 0)
                    cloud_cover = current.get("cloud_cover", 0)

                    # Derive fog_factor: fog/rime-fog weather codes → 1.0,
                    # otherwise scale cloud_cover (0-100) to 0.0-0.3, capped at 1.0
                    if weather_code in _FOG_WEATHER_CODES:
                        fog_factor = 1.0
                    else:
                        fog_factor = min((cloud_cover or 0) / 100.0 * 0.3, 1.0)

                    obs: dict[str, Any] = {
                        "station_id": name,
                        "temperature_c": temperature_c,
                        "wind_speed_kmh": wind_speed_kmh,
                        "precipitation_mm": precipitation_mm or 0.0,
                        "visibility_m": visibility_m,
                        "cloud_cover_pct": cloud_cover,
                        "fog_factor": fog_factor,
                        "source": "open_meteo",
                    }
                    results.append(obs)

                    # Build InfluxDB line protocol
                    fields: list[str] = []
                    if temperature_c is not None:
                        fields.append(f"temperature_c={temperature_c}")
                    if wind_speed_kmh is not None:
                        fields.append(f"wind_speed_kmh={wind_speed_kmh}")
                    fields.append(f"precipitation_mm={precipitation_mm or 0.0}")
                    if visibility_m is not None:
                        fields.append(f"visibility_m={visibility_m}")
                    fields.append(f"cloud_cover_pct={cloud_cover}")
                    fields.append(f"fog_factor={fog_factor}")

                    if fields:
                        tag_name = name.replace(" ", r"\ ")
                        line = (
                            f"weather,station_id={tag_name},source=open_meteo "
                            + ",".join(fields)
                        )
                        await write_points(line)
                except Exception:
                    self.logger.warning(
                        "Failed to parse Open-Meteo response for location %s", name
                    )

        return results


class CombinedWeatherIngestor(BaseIngestor):
    """Aggregates NOAA, AEMET, and Open-Meteo ingestors into a single interface."""

    def __init__(
        self,
        noaa_stations: list[str] | None = None,
        aemet_stations: list[str] | None = None,
        open_meteo_locations: list[dict] | None = None,
    ) -> None:
        super().__init__(name="weather")
        self.noaa = NOAAWeatherIngestor(station_ids=noaa_stations)
        self.aemet = AEMETWeatherIngestor(station_ids=aemet_stations)
        self.open_meteo = OpenMeteoIngestor(locations=open_meteo_locations)

    async def start(self) -> None:
        self._running = True
        await self.noaa.start()
        await self.aemet.start()
        await self.open_meteo.start()

    async def stop(self) -> None:
        self._running = False
        await self.noaa.stop()
        await self.aemet.stop()
        await self.open_meteo.stop()

    async def poll(self) -> list[dict[str, Any]]:
        noaa_results = await self.noaa.poll()
        aemet_results = await self.aemet.poll()
        open_meteo_results = await self.open_meteo.poll()
        return noaa_results + aemet_results + open_meteo_results
