from __future__ import annotations

from use.models.ingestion import IngestionRecord
from use.models.lakehouse import LakehouseRecord


class StructuringPipeline:
    """
    Raw → Structured → Semantic promotion pipeline.

    Phase 0: stubs only. Each stage returns None until implemented.
    """

    async def raw_to_structured(self, record: IngestionRecord) -> dict | None:
        """Parse raw payload into structured form. Returns structured dict or None."""
        return None

    async def structured_to_semantic(self, structured: dict, record: IngestionRecord) -> LakehouseRecord | None:
        """Extract semantic content and build MD + Graph layers."""
        return None

    async def process(self, record: IngestionRecord) -> LakehouseRecord | None:
        """Full pipeline: raw → structured → semantic."""
        structured = await self.raw_to_structured(record)
        if structured is None:
            return None
        return await self.structured_to_semantic(structured, record)
