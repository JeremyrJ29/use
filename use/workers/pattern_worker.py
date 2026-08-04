"""
Pattern worker — subscribes to ``use.pattern.analyze`` and runs the pattern
detection engine on demand.  Also runs a scheduled loop every 60 seconds.

Errors are logged and swallowed — this worker must never crash ingestion.
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any

import structlog

from use.bus.nats_bus import NatsBus
from use.config import get_settings
from use.db.postgres import AsyncSessionLocal
from use.services import pattern_service

logger: structlog.BoundLogger = structlog.get_logger(__name__)
settings = get_settings()

ANALYZE_SUBJECT = "use.pattern.analyze"
RESULTS_SUBJECT = "use.pattern.results"
SCHEDULE_INTERVAL = 60  # seconds


async def _run_analysis(bus: NatsBus) -> dict:
    """Open a DB session, run all pattern detectors, publish the result."""
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                summary = await pattern_service.run_pattern_analysis(db)
        await bus.publish(RESULTS_SUBJECT, summary)
        logger.info("pattern_worker: analysis complete", **summary)
        return summary
    except Exception as exc:
        logger.error("pattern_worker: analysis failed", error=str(exc))
        return {}


class PatternWorker:
    """
    NATS-backed worker that handles ``use.pattern.analyze`` messages and
    runs a scheduled loop every 60 seconds.
    """

    def __init__(self) -> None:
        self._running = False
        self._bus = NatsBus()

    async def start(self) -> None:
        self._running = True
        await self._bus.connect()
        logger.info("pattern_worker: connected to NATS")

        import nats as nats_lib

        nc: nats_lib.aio.client.Client = self._bus._nc  # type: ignore[union-attr]

        async def _dispatch(msg: Any) -> None:
            logger.info("pattern_worker: received analyze request")
            await _run_analysis(self._bus)

        sub = await nc.subscribe(ANALYZE_SUBJECT, cb=_dispatch)

        loop = asyncio.get_running_loop()

        def _shutdown(_: Any) -> None:
            logger.info("pattern_worker: shutdown signal received")
            loop.create_task(self.stop())

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown, sig)
            except (NotImplementedError, ValueError):
                pass

        # Scheduled loop
        async def _scheduler() -> None:
            while self._running:
                await asyncio.sleep(SCHEDULE_INTERVAL)
                if self._running:
                    logger.info("pattern_worker: scheduled analysis triggered")
                    await _run_analysis(self._bus)

        scheduler_task = asyncio.ensure_future(_scheduler())

        logger.info("pattern_worker: listening on %s, interval=%ds", ANALYZE_SUBJECT, SCHEDULE_INTERVAL)
        try:
            while self._running:
                await asyncio.sleep(0.5)
        finally:
            scheduler_task.cancel()
            await sub.unsubscribe()
            await self._bus.disconnect()
            logger.info("pattern_worker: stopped")

    async def stop(self) -> None:
        self._running = False
        logger.info("pattern_worker: stop requested")


# ---------------------------------------------------------------------------
# Standalone entry-point
# ---------------------------------------------------------------------------


async def _main() -> None:
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    worker = PatternWorker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(_main())
