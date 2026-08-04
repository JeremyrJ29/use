from __future__ import annotations

import logging

from use.models.lakehouse import LakehouseRecord

logger = logging.getLogger(__name__)


class GraphBuilder:
    """
    Builds graph nodes and edges from structured/semantic documents.
    Delegates to graph_service.build_from_document for real implementation.
    """

    async def build_from_lakehouse(self, record: LakehouseRecord, db=None) -> None:
        """Derive graph nodes/edges from a LakehouseRecord's MD layer content."""
        if db is None:
            logger.warning("GraphBuilder.build_from_lakehouse: no db session provided for %s", record.use_doc_id)
            return
        from use.services import graph_service
        await graph_service.build_from_document(record, db)
