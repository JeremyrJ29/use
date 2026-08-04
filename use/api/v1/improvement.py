"""
improvement.py — REST API for the Continuous Improvement Loop log.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from use.db.postgres import get_db
from use.services import improvement_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/improvement/stats", tags=["improvement"])
async def improvement_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """Counts by trigger_type + status."""
    return await improvement_service.get_improvement_stats(db)


@router.get("/improvement/{log_id}", tags=["improvement"])
async def get_improvement_record(log_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Single improvement_log record."""
    result = await db.execute(
        text("""
            SELECT id, trigger_type, trigger_id, affected_doc_ids, changes,
                   status, started_at, completed_at, created_at, error
            FROM improvement_log WHERE id = :id
        """),
        {"id": str(log_id)},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"improvement log {log_id} not found")
    r = dict(row)
    r["id"] = str(r["id"])
    r["trigger_id"] = str(r["trigger_id"])
    r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
    r["started_at"] = r["started_at"].isoformat() if r.get("started_at") else None
    r["completed_at"] = r["completed_at"].isoformat() if r.get("completed_at") else None
    return r


@router.get("/improvement", tags=["improvement"])
async def list_improvement_log(
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List recent improvement_log records (paginated, last 100 by default)."""
    items = await improvement_service.get_improvement_log(limit, db)
    return {"items": items, "total": len(items), "limit": limit}


@router.post("/improvement/reindex", tags=["improvement"])
async def trigger_reindex(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Admin: trigger full re-ingestion of all lakehouse_records.
    Requires write scope. Runs asynchronously via NATS.
    """
    # Count docs to reindex
    result = await db.execute(text("SELECT COUNT(*) FROM lakehouse_records"))
    total = result.scalar() or 0

    # Publish reindex message to NATS (fire-and-forget)
    try:
        from use.bus.nats_bus import NatsBus
        from use.config import get_settings
        bus = NatsBus(get_settings().nats_url)
        await bus.publish("use.improvement.reindex", {"action": "reindex", "total_docs": total})
    except Exception as exc:
        logger.warning("trigger_reindex: NATS publish failed (%s), scheduling inline", exc)
        # Fall back to direct async task
        import asyncio
        from use.db.postgres import AsyncSessionLocal

        async def _inline_reindex() -> None:
            try:
                result2 = await db.execute(text("SELECT id FROM lakehouse_records ORDER BY created_at DESC"))
                doc_ids = [str(row[0]) for row in result2.fetchall()]
                for doc_id in doc_ids:
                    try:
                        async with AsyncSessionLocal() as idb:
                            async with idb.begin():
                                await improvement_service.reprocess_document(doc_id, idb)
                    except Exception as exc2:
                        logger.warning("inline reindex: error for %s: %s", doc_id, exc2)
            except Exception as exc3:
                logger.error("inline reindex: failed: %s", exc3)

        asyncio.create_task(_inline_reindex())

    return {"triggered": True, "job_count": total, "message": f"Reindex queued for {total} documents"}
