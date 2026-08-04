"""PDF connector — extracts text page-by-page via pypdf and yields one IngestionRecord per page."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

from use.connectors.base import Connector
from use.models.ingestion import IngestionRecord

logger = logging.getLogger(__name__)


class PDFConnector(Connector):
    """
    Reads a PDF file and converts each page to an IngestionRecord.

    Uses *pypdf* for text extraction.  Encrypted or corrupted pages are
    skipped with a warning rather than crashing the run.

    Config
    ------
    file_path : str   Path to the PDF file.
    """

    source_type = "pdf"

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def health_check(self) -> bool:
        return os.path.exists(self.file_path)

    async def read(self) -> list[dict[str, Any]]:
        """Return list of {page_number, text} dicts."""
        from pypdf import PdfReader  # type: ignore[import-untyped]

        pages: list[dict[str, Any]] = []
        try:
            reader = PdfReader(self.file_path)
            if reader.is_encrypted:
                logger.warning("PDFConnector: %s is encrypted — skipping", self.file_path)
                return pages
            for i, page in enumerate(reader.pages):
                try:
                    text = page.extract_text() or ""
                    pages.append({"page_number": i + 1, "text": text})
                except Exception as exc:
                    logger.warning("PDFConnector: failed to extract page %d: %s", i + 1, exc)
        except Exception as exc:
            logger.error("PDFConnector.read failed for %s: %s", self.file_path, exc)
        return pages

    async def pull(self) -> list[IngestionRecord]:
        """Read the PDF and return one IngestionRecord per page."""
        from pypdf import PdfReader  # type: ignore[import-untyped]

        records: list[IngestionRecord] = []
        try:
            reader = PdfReader(self.file_path)
            if reader.is_encrypted:
                logger.warning("PDFConnector: %s is encrypted — cannot pull", self.file_path)
                return records
            total_pages = len(reader.pages)
            for i, page in enumerate(reader.pages):
                try:
                    text = page.extract_text() or ""
                    records.append(
                        IngestionRecord(
                            id=uuid4(),
                            source_id=self.file_path,
                            source_type="pdf",
                            ingested_at=datetime.utcnow(),
                            raw_payload=text,
                            encoding="utf-8",
                            byte_size=len(text.encode()),
                            metadata={
                                "origin": self.file_path,
                                "page_number": i + 1,
                                "total_pages": total_pages,
                            },
                        )
                    )
                except Exception as exc:
                    logger.warning("PDFConnector: skipping page %d: %s", i + 1, exc)
        except Exception as exc:
            logger.error("PDFConnector.pull failed for %s: %s", self.file_path, exc)
        return records
