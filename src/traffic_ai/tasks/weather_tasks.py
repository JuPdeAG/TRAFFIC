"""Celery tasks for weather data ingestion."""
from __future__ import annotations
import asyncio
import logging
from traffic_ai.celery_app import app
from traffic_ai.config import settings

logger = logging.getLogger(__name__)


@app.task(name="traffic_ai.tasks.weather_tasks.poll_weather")
def poll_weather(source: str = "noaa", station_id: str = "") -> dict:
    """Poll a single weather station."""
    if source == "noaa":
        from traffic_ai.ingestors.weather import NOAAWeatherIngestor
        ingestor = NOAAWeatherIngestor(station_ids=[station_id] if station_id else [])
    else:
        from traffic_ai.ingestors.weather import AEMETWeatherIngestor
        ingestor = AEMETWeatherIngestor(station_ids=[station_id] if station_id else [])
    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(ingestor.poll())
    finally:
        loop.close()
    return {"source": source, "observations": len(results)}


@app.task(name="traffic_ai.tasks.weather_tasks.poll_all_weather")
def poll_all_weather() -> dict:
    """Poll all configured weather sources."""
    from traffic_ai.ingestors.weather import CombinedWeatherIngestor
    noaa_stations = settings.noaa_station_list
    aemet_stations = settings.aemet_station_list
    logger.info(
        "Polling all weather sources (NOAA stations=%d, AEMET stations=%d)",
        len(noaa_stations), len(aemet_stations),
    )
    ingestor = CombinedWeatherIngestor(
        noaa_stations=noaa_stations,
        aemet_stations=aemet_stations,
    )
    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(ingestor.poll())
    finally:
        loop.close()
    return {"total_observations": len(results)}
