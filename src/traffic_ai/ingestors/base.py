"""Abstract base class for all data ingestors."""
from __future__ import annotations
import abc
import logging
from typing import Any


class BaseIngestor(abc.ABC):
    """Interface that all ingestors must implement."""
    def __init__(self, name: str = "base") -> None:
        self.name = name
        self.logger = logging.getLogger(f"ingestor.{name}")
        self._running = False

    @abc.abstractmethod
    async def start(self) -> None:
        """Begin ingesting data."""
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        """Gracefully stop ingestion."""
        ...

    @abc.abstractmethod
    async def poll(self) -> list[dict[str, Any]]:
        """Poll for new data and return parsed records."""
        ...

    @property
    def is_running(self) -> bool:
        return self._running
