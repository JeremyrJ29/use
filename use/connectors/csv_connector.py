"""CSV connector — reads a delimited text file and yields one IngestionRecord per row."""
from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

from use.connectors.base import Connector
from use.models.ingestion import IngestionRecord

logger = logging.getLogger(__name__)


class CSVConnector(Connector):
    """
    Reads a CSV file from disk and converts each data row to an IngestionRecord.

    Config
    ------
    file_path : str   Path to the CSV file.
    delimiter : str   Field delimiter (default ',').
    encoding  : str   File encoding (default 'utf-8').
    """

    source_type = "csv"

    def __init__(
        self,
        file_path: str,
        delimiter: str = ",",
        encoding: str = "utf-8",
    ) -> None:
        self.file_path = file_path
        self.delimiter = delimiter
        self.encoding = encoding

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def health_check(self) -> bool:
        return os.path.exists(self.file_path)

    async def read(self) -> list[dict[str, Any]]:
        """Return raw row dicts from the CSV (used internally)."""
        rows: list[dict[str, Any]] = []
        try:
            with open(self.file_path, newline="", encoding=self.encoding, errors="replace") as fh:
                reader = csv.DictReader(fh, delimiter=self.delimiter)
                for row in reader:
                    rows.append(dict(row))
        except Exception as exc:
            logger.error("CSVConnector.read failed: %s", exc)
        return rows

    async def pull(self) -> list[IngestionRecord]:
        """Read the CSV file and return one IngestionRecord per data row."""
        records: list[IngestionRecord] = []
        try:
            with open(self.file_path, newline="", encoding=self.encoding, errors="replace") as fh:
                reader = csv.DictReader(fh, delimiter=self.delimiter)
                columns = list(reader.fieldnames or [])
                rows = [dict(row) for row in reader]

            row_count = len(rows)
            for row in rows:
                payload = json.dumps(row)
                records.append(
                    IngestionRecord(
                        id=uuid4(),
                        source_id=self.file_path,
                        source_type="csv",
                        ingested_at=datetime.utcnow(),
                        raw_payload=payload,
                        encoding="utf-8",
                        byte_size=len(payload.encode()),
                        metadata={
                            "origin": self.file_path,
                            "row_count": row_count,
                            "columns": columns,
                        },
                    )
                )
        except Exception as exc:
            logger.error("CSVConnector.pull failed for %s: %s", self.file_path, exc)
        return records
