"""
Ingestion worker — subscribes to the NATS subject ``use.ingest.*`` and
drives each received IngestionRecord through the structuring pipeline.

On success  : publishes a summary to ``use.lakehouse.new``.
On failure  : publishes an error envelope to ``use.ingest.dlq``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any

import nats
from nats.aio.msg import Msg

from use.bus.nats_bus import NatsBus
from use.config import get_settings
from use.db.postgres import AsyncSessionLocal
from use.models.ingestion import IngestionRecord
from use.services import structuring

logger = logging.getLogger(__name__)
settings = get_settings()

INGEST_SUBJECT = "use.ingest.*"
LAKEHOUSE_SUBJECT = "use.lakehouse.new"
DLQ_SUBJECT = "use.ingest.dlq"


async def _handle_message(msg: Msg, bus: NatsBus) -> None:
    """Process a single NATS message containing an IngestionRecord payload."""
    try:
        data: dict[str, Any] = json.loads(msg.data.decode())
        record = IngestionRecord.model_validate(data)
    except Exception as exc:
        logger.error("IngestionWorker: failed to deserialize message: %s", exc)
        await bus.publish(DLQ_SUBJECT, {"error": str(exc), "raw": msg.data.decode(errors="replace")})
        return

    logger.info("IngestionWorker: processing record=%s source_type=%s", record.id, record.source_type)

    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                lakehouse = await structuring.process(record, db)

        summary = {
            "use_doc_id": str(lakehouse.use_doc_id),
            "ingestion_record_id": str(lakehouse.ingestion_record_id),
            "source_id": lakehouse.source_id,
            "word_count": lakehouse.md_layer.word_count,
        }
        await bus.publish(LAKEHOUSE_SUBJECT, summary)
        logger.info("IngestionWorker: completed doc=%s", lakehouse.use_doc_id)

    except Exception as exc:
        logger.exception("IngestionWorker: pipeline error for record=%s: %s", record.id, exc)
        try:
            await bus.publish(
                DLQ_SUBJECT,
                {
                    "record_id": str(record.id),
                    "source_id": record.source_id,
                    "error": str(exc),
                },
            )
        except Exception as pub_exc:
            logger.error("IngestionWorker: failed to publish to DLQ: %s", pub_exc)


class IngestionWorker:
    """
    NATS-backed worker that consumes ``use.ingest.*`` and runs the
    structuring pipeline for every message.

    Usage::

        worker = IngestionWorker()
        await worker.start()
        # runs until SIGINT / SIGTERM
    """

    def __init__(self) -> None:
        self._running = False
        self._bus = NatsBus()

    async def start(self) -> None:
        self._running = True
        await self._bus.connect()
        logger.info("IngestionWorker: connected to NATS, subscribing to %s", INGEST_SUBJECT)

        nc: nats.aio.client.Client = self._bus._nc  # type: ignore[union-attr]

        async def _dispatch(msg: Msg) -> None:
            await _handle_message(msg, self._bus)

        sub = await nc.subscribe(INGEST_SUBJECT, cb=_dispatch)

        loop = asyncio.get_running_loop()

        def _shutdown(_: Any) -> None:
            logger.info("IngestionWorker: shutdown signal received")
            loop.create_task(self.stop())

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown, sig)
            except (NotImplementedError, ValueError):
                pass  # Windows does not support add_signal_handler for all signals

        logger.info("IngestionWorker: listening for messages")
        try:
            while self._running:
                await asyncio.sleep(0.5)
        finally:
            await sub.unsubscribe()
            await self._bus.disconnect()
            logger.info("IngestionWorker: stopped")

    async def stop(self) -> None:
        self._running = False
        logger.info("IngestionWorker: stop requested")


# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------


async def _main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    worker = IngestionWorker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(_main())

