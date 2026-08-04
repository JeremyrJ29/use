from __future__ import annotations

import logging

from use.models.lakehouse import LakehouseRecord

logger = logging.getLogger(__name__)


class GraphBuilder:
    """
    Builds graph nodes and edges in Neo4j from structured/semantic documents.

    Phase 0: stub. Neo4j writes added in Phase 1.
    """

    async def build_from_lakehouse(self, record: LakehouseRecord) -> None:
        """Derive graph nodes/edges from a LakehouseRecord's MD layer content."""
        logger.debug("GraphBuilder.build_from_lakehouse called (stub) for %s", record.use_doc_id)
