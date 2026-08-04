from __future__ import annotations

import logging

from use.services.structuring import StructuringPipeline

logger = logging.getLogger(__name__)


class IngestionWorker:
    """
    Consumes ingestion queue messages, routes records through the structuring pipeline.

    Phase 0: stub. Actual NATS subscription and DB writes added in Phase 1.
    """

    def __init__(self) -> None:
        self.pipeline = StructuringPipeline()
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("IngestionWorker started (stub — no-op)")

    async def stop(self) -> None:
        self._running = False
        logger.info("IngestionWorker stopped")
