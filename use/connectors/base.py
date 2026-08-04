from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Connector(ABC):
    """Abstract base class for all USE data source connectors."""

    source_type: str = "base"

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the data source."""
        ...

    @abstractmethod
    async def read(self) -> list[dict[str, Any]]:
        """Read records from the data source. Returns list of raw record dicts."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the data source."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the data source is reachable."""
        ...

    @classmethod
    def list_available(cls) -> list[str]:
        """Return list of available connector source_type strings."""
        return [sub.source_type for sub in cls.__subclasses__()]
