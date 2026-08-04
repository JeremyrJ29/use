"""Health-check endpoint — verifies connectivity to Postgres, Neo4j, Redis, and NATS."""
from __future__ import annotations

import logging

from fastapi import APIRouter

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", tags=["health"])
async def health_check() -> dict:
    """
    Probe all downstream services and return a status summary.

    Returns HTTP 200 even when some checks fail so callers can inspect
    individual service states without relying on HTTP status codes.
    """
    checks: dict[str, bool] = {}

    # --- Postgres ---
    try:
        from sqlalchemy import text

        from use.db.postgres import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["postgres"] = True
    except Exception as exc:
        logger.warning("health: postgres check failed: %s", exc)
        checks["postgres"] = False

    # --- Neo4j ---
    try:
        from use.db.neo4j import get_driver

        driver = get_driver()
        async with driver.session() as neo_session:
            await neo_session.run("RETURN 1")
        checks["neo4j"] = True
    except Exception as exc:
        logger.warning("health: neo4j check failed: %s", exc)
        checks["neo4j"] = False

    # --- Redis ---
    try:
        from use.db.redis import get_redis_client

        redis_client = get_redis_client()
        await redis_client.ping()
        checks["redis"] = True
    except Exception as exc:
        logger.warning("health: redis check failed: %s", exc)
        checks["redis"] = False

    # --- NATS ---
    try:
        from use.bus.nats_bus import NatsBus

        bus = NatsBus()
        await bus.connect()
        await bus.disconnect()
        checks["nats"] = True
    except Exception as exc:
        logger.warning("health: nats check failed: %s", exc)
        checks["nats"] = False

    # --- Catalog stats ---
    catalog_stats: dict = {}
    if checks.get("postgres"):
        try:
            from use.db.postgres import AsyncSessionLocal
            from use.services import catalog_service

            async with AsyncSessionLocal() as db:
                stats = await catalog_service.compute_catalog_stats(db)
            catalog_stats = {
                "total_entities": stats["total_entities"],
                "confirmed": stats["confirmed_count"],
                "unconfirmed": stats["unconfirmed_count"],
            }
        except Exception as exc:
            logger.warning("health: catalog stats failed: %s", exc)
            catalog_stats = {}

    overall = "ok" if all(checks.values()) else "degraded"
    response: dict = {"status": overall, "checks": checks}
    if catalog_stats:
        response["catalog"] = catalog_stats
    return response
