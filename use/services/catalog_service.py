from __future__ import annotations

from use.models.catalog import CatalogEntry
from use.models.ingestion import IngestionRecord


class CatalogService:
    """
    Entity extraction and cross-reference mapping service.

    Phase 0: stubs only.
    """

    async def extract_entities(self, record: IngestionRecord) -> list[CatalogEntry]:
        """Extract canonical entities from an ingestion record."""
        return []

    async def cross_reference(self, entry: CatalogEntry) -> list[CatalogEntry]:
        """Find existing catalog entries that may represent the same entity."""
        return []

    async def update_occurrence(self, canonical_id: str) -> None:
        """Increment occurrence count and update last_seen for a catalog entry."""
        pass

    async def confirm_entry(self, canonical_id: str, reviewer_id: str) -> CatalogEntry | None:
        """Human-confirm a catalog entry."""
        return None
