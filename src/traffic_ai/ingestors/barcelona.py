"""Barcelona traffic state ingestor.

Pulls real-time traffic state data from Open Data BCN (Ajuntament de Barcelona).
Data is published every 5 minutes from inductive loop sensors on the urban network.

API: Open Data BCN CKAN portal — dataset "Trams de vies amb estat del trànsit"
Resource URL:  https://opendata-ajuntament.barcelona.cat/data/api/action/datastore_search
Dataset ID:    trams (traffic sections with current state)

Each road section ("tram") has:
    idTram          — section ID
    descripcio      — human-readable location (e.g. "Gran Via - Balmes / Enric Granados")
    estatActual     — current state: 0=no data, 1=very fluid, 2=fluid, 3=dense, 4=very dense, 5=congested, 6=cut
    velocitat       — average speed km/h (may be absent for low-traffic sensors)

We map estat 0–6 to our density_score 0–100 and write to InfluxDB measurement
"barcelona_traffic" so the risk scorer can use it.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from traffic_ai.db.influx import write_points
from traffic_ai.ingestors.base import BaseIngestor

logger = logging.getLogger(__name__)

# Barcelona open data publishes a real-time .dat file (updated every ~5 min).
# Format: tram_id#timestamp#current_state#expected_state   (hash-delimited)
# State codes: 0=no data, 1=very fluid, 2=fluid, 3=dense, 4=very dense, 5=congested, 6=closed
BCN_TRAMS_DAT_URL = (
    "https://opendata-ajuntament.barcelona.cat/data/dataset/"
    "8319c2b1-4c21-4962-9acd-6/resource/2d456eb5-4ea6-4f68-9794-2f3f1a58a933"
    "/download/TRAMS_TRAMS.dat"
)

# estat → density score (0-100)
_ESTAT_TO_SCORE: dict[int, float] = {
    0: 0.0,   # no data
    1: 10.0,  # very fluid
    2: 25.0,  # fluid
    3: 50.0,  # dense
    4: 65.0,  # very dense
    5: 80.0,  # congested
    6: 100.0, # cut / road closed
}

_ESTAT_TO_LEVEL: dict[int, str] = {
    0: "unknown",
    1: "free_flow",
    2: "light",
    3: "moderate",
    4: "heavy",
    5: "congested",
    6: "closed",
}


class BarcelonaIngestor(BaseIngestor):
    """Ingests Barcelona real-time traffic state from Open Data BCN.

    Fetches the TRAMS_TRAMS.dat file which is updated every ~5 minutes.
    Format: tram_id#timestamp#current_state#expected_state  (hash-delimited)
    """

    def __init__(self) -> None:
        super().__init__(name="barcelona")

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[dict[str, Any]]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    BCN_TRAMS_DAT_URL, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        self.logger.warning("Barcelona .dat returned HTTP %d", resp.status)
                        return []
                    text = await resp.text(encoding="utf-8", errors="replace")
        except Exception:
            self.logger.exception("Failed to fetch Barcelona TRAMS_TRAMS.dat")
            return []

        records = _parse_dat(text)
        if not records:
            return []

        lines = [_to_line_protocol(r) for r in records]
        try:
            await write_points(lines)
            self.logger.info("Barcelona: wrote %d traffic state points", len(lines))
        except Exception:
            self.logger.exception("Failed to write Barcelona traffic data")

        return records

def _parse_dat(text: str) -> list[dict[str, Any]]:
    """Parse Barcelona TRAMS_TRAMS.dat: tram_id#timestamp#current_state#expected_state."""
    records: list[dict[str, Any]] = []
    ts = datetime.now(timezone.utc)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("#")
        if len(parts) < 3:
            continue
        try:
            tram_id = parts[0].strip()
            estat = int(parts[2].strip())
            records.append({
                "tram_id": f"bcn_{tram_id}",
                "estat": estat,
                "speed_kmh": 0.0,
                "density_score": _ESTAT_TO_SCORE.get(estat, 0.0),
                "density_level": _ESTAT_TO_LEVEL.get(estat, "unknown"),
                "source": "barcelona_open_data",
                "ts": ts,
            })
        except (ValueError, IndexError):
            continue
    return records


def _to_line_protocol(record: dict[str, Any]) -> str:
    tram_id = record["tram_id"].replace(" ", r"\ ")
    return (
        f"barcelona_traffic,tram_id={tram_id},source=barcelona "
        f"density_score={record['density_score']},"
        f"speed_kmh={record['speed_kmh']},"
        f"estat={record['estat']}i"
    )
