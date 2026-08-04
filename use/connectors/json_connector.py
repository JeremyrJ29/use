from __future__ import annotations

from typing import Any

from use.connectors.base import Connector


class JSONConnector(Connector):
    """JSON connector stub."""

    source_type = "api"

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    async def connect(self) -> None:
        pass

    async def read(self) -> list[dict[str, Any]]:
        return []

    async def disconnect(self) -> None:
        pass

    async def health_check(self) -> bool:
        import os
        return os.path.exists(self.file_path)
