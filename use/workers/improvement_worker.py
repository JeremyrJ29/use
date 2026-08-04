"""
improvement_worker.py — NATS subscriber for the Continuous Improvement Loop.

Subjects:
  use.improvement.*      — route a review approval to improvement_service
  use.improvement.reindex — admin-triggered full re-ingestion of all docs
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
from use.services import improvement_service

logger = logging.getLogger(__name__)
settings = get_settings()

IMPROVEMENT_SUBJECT = "use.improvement.*"
RESULTS_SUBJECT = "use.improvement.results"
REINDEX_SUBJECT = "use.improvement.reindex"


async def _handle_improvement(msg: Msg, bus: NatsBus) -> None:
    """Route a review-approval message to the appropriate improvement handler."""
    subject = msg.subject
    try:
        data: dict[str, Any] = json.loads(msg.data.decode())
    except Exception as exc:
        logger.error("ImprovementWorker: deserialize error on %s: %s", subject, exc)
        return

    logger.info("ImprovementWorker: received %s payload=%s", subject, list(data.keys()))

    # Full reindex request
    if subject == REINDEX_SUBJECT or data.get("action") == "reindex":
        await _handle_reindex(bus)
        return

    # Normal improvement routing
    review_item = data.get("review_item") or data
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                result = await improvement_service.route_improvement(review_item, db)

        await bus.publish(RESULTS_SUBJECT, {
            "subject": subject,
            "review_item_id": review_item.get("id"),
            "result": result,
        })
        logger.info("ImprovementWorker: completed %s result=%s", subject, result)
    except Exception as exc:
        logger.error("ImprovementWorker: handler error on %s: %s", subject, exc)
        # Swallow — never crash the worker


async def _handle_reindex(bus: NatsBus) -> None:
    """Admin-triggered full re-ingestion of all lakehouse_records."""
    logger.info("ImprovementWorker: starting full reindex")
    total = 0
    errors = 0

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                __import__("sqlalchemy").text("SELECT id FROM lakehouse_records ORDER BY created_at DESC")
            )
            doc_ids = [str(row[0]) for row in result.fetchall()]

        for doc_id in doc_ids:
            try:
                async with AsyncSessionLocal() as db:
                    async with db.begin():
                        await improvement_service.reprocess_document(doc_id, db)
                total += 1
            except Exception as exc:
                logger.warning("ImprovementWorker reindex: error for doc %s: %s", doc_id, exc)
                errors += 1

    except Exception as exc:
        logger.error("ImprovementWorker reindex: failed to list docs: %s", exc)

    await bus.publish(RESULTS_SUBJECT, {
        "action": "reindex_complete",
        "total_processed": total,
        "errors": errors,
    })
    logger.info("ImprovementWorker: reindex complete total=%s errors=%s", total, errors)


async def run() -> None:
    """Main entry-point — connect to NATS and subscribe."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    bus = NatsBus(settings.nats_url)

    stop_event = asyncio.Event()

    def _handle_sigterm(*_: Any) -> None:
        logger.info("ImprovementWorker: SIGTERM received, shutting down")
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    logger.info("ImprovementWorker: connecting to %s", settings.nats_url)
    nc = await nats.connect(settings.nats_url)

    async def _dispatch(msg: Msg) -> None:
        await _handle_improvement(msg, bus)

    sub = await nc.subscribe(IMPROVEMENT_SUBJECT, cb=_dispatch)
    logger.info("ImprovementWorker: subscribed to %s", IMPROVEMENT_SUBJECT)

    await stop_event.wait()

    logger.info("ImprovementWorker: draining subscriptions")
    await sub.unsubscribe()
    await nc.drain()
    logger.info("ImprovementWorker: shutdown complete")


if __name__ == "__main__":
    asyncio.run(run())
