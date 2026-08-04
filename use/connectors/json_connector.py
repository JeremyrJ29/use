"""JSON connector — reads a JSON file or string and yields one IngestionRecord per item."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

from use.connectors.base import Connector
from use.models.ingestion import IngestionRecord

logger = logging.getLogger(__name__)


class JSONConnector(Connector):
    """
    Reads JSON from a file path or an inline JSON string.

    - Top-level list  → one IngestionRecord per element.
    - Top-level dict  → a single IngestionRecord for the whole object.

    Config
    ------
    file_path     : str | None   Path to a JSON file (mutually exclusive with json_string).
    json_string   : str | None   Raw JSON text (mutually exclusive with file_path).
    """

    source_type = "json"

    def __init__(
        self,
        file_path: str | None = None,
        json_string: str | None = None,
    ) -> None:
        if file_path is None and json_string is None:
            raise ValueError("JSONConnector requires either file_path or json_string")
        self.file_path = file_path
        self.json_string = json_string

    @property
    def _origin(self) -> str:
        return self.file_path or "<inline>"

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def health_check(self) -> bool:
        if self.file_path:
            return os.path.exists(self.file_path)
        return self.json_string is not None

    def _load_raw(self) -> Any:
        if self.json_string is not None:
            return json.loads(self.json_string)
        with open(self.file_path, encoding="utf-8") as fh:  # type: ignore[arg-type]
            return json.load(fh)

    async def read(self) -> list[dict[str, Any]]:
        """Return list of raw dicts."""
        try:
            data = self._load_raw()
            if isinstance(data, list):
                return [item if isinstance(item, dict) else {"value": item} for item in data]
            if isinstance(data, dict):
                return [data]
            return [{"value": data}]
        except Exception as exc:
            logger.error("JSONConnector.read failed for %s: %s", self._origin, exc)
            return []

    async def pull(self) -> list[IngestionRecord]:
        """Parse JSON and return IngestionRecords."""
        records: list[IngestionRecord] = []
        try:
            data = self._load_raw()
            items: list[Any] = data if isinstance(data, list) else [data]
            item_count = len(items)
            for item in items:
                payload = json.dumps(item)
                records.append(
                    IngestionRecord(
                        id=uuid4(),
                        source_id=self._origin,
                        source_type="json",
                        ingested_at=datetime.utcnow(),
                        raw_payload=payload,
                        encoding="utf-8",
                        byte_size=len(payload.encode()),
                        metadata={"origin": self._origin, "item_count": item_count},
                    )
                )
        except Exception as exc:
            logger.error("JSONConnector.pull failed for %s: %s", self._origin, exc)
        return records
