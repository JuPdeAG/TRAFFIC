"""InfluxDB async client wrapper."""
from __future__ import annotations
import logging
from typing import Any
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from traffic_ai.config import settings

logger = logging.getLogger(__name__)
_client: InfluxDBClientAsync | None = None


def get_influx_client() -> InfluxDBClientAsync:
    """Return a singleton InfluxDB async client."""
    global _client
    if _client is None:
        _client = InfluxDBClientAsync(url=settings.influx_url, token=settings.influx_token, org=settings.influx_org)
    return _client


async def write_points(record: str | list[str], bucket: str | None = None) -> None:
    """Write line-protocol points to InfluxDB."""
    client = get_influx_client()
    write_api = client.write_api()
    await write_api.write(bucket=bucket or settings.influx_bucket, record=record)


async def query_points(query: str, bucket: str | None = None) -> list[dict[str, Any]]:
    """Execute a Flux query and return results as a list of dicts."""
    client = get_influx_client()
    query_api = client.query_api()
    tables = await query_api.query(query)
    results: list[dict[str, Any]] = []
    for table in tables:
        for record in table.records:
            results.append(record.values)
    return results
