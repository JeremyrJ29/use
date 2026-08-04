from __future__ import annotations

import asyncio
import json
import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


from use.db.postgres import get_db
from use.models.review import ReviewItem
from use.services import graph_service
from use.services import improvement_service

logger = logging.getLogger(__name__)

router = APIRouter()


class ReviewUpdateBody(BaseModel):
    notes: str | None = None
    payload: dict[str, Any] | None = None


class RejectBody(BaseModel):
    notes: str | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_review(row: Any) -> dict:
    return {
        "id": str(row["id"]),
        "queue": row["queue"],
        "status": row["status"],
        "payload": row["payload"],
        "reviewer_id": row["reviewer_id"],
        "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
        "notes": row["notes"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def _list_queue(
    queue: str | None,
    page: int,
    limit: int,
    db: AsyncSession,
) -> dict:
    offset = (page - 1) * limit
    params: dict = {"limit": limit, "offset": offset}

    where = "status = 'pending'"
    if queue is not None:
        where += " AND queue = :queue"
        params["queue"] = queue

    total_result = await db.execute(
        text(f"SELECT COUNT(*) FROM review_items WHERE {where}"), params
    )
    total = total_result.scalar()

    rows_result = await db.execute(
        text(f"""
            SELECT * FROM review_items
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [_row_to_review(r) for r in rows_result.mappings().all()]
    return {"items": items, "total": total, "page": page, "limit": limit}


async def _write_audit(action: str, entity_id: str, user_id: str | None, detail: dict, db: AsyncSession) -> None:
    await db.execute(
        text("""
            INSERT INTO audit_log (id, action, entity_type, entity_id, user_id, detail, created_at)
            VALUES (:id, :action, 'review_item', :entity_id, :user_id, :detail, NOW())
        """),
        {
            "id": str(_uuid.uuid4()),
            "action": action,
            "entity_id": entity_id,
            "user_id": user_id,
            "detail": json.dumps(detail),
        },
    )


@router.post("/anomalies/{anomaly_id}/acknowledge", tags=["review"])
async def acknowledge_anomaly(
    anomaly_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Acknowledge an anomaly: mark edge acknowledged + review_item approved."""
    row = await db.execute(
        text("SELECT id, payload, status FROM review_items WHERE id = :id AND queue = 'anomaly'"),
        {"id": str(anomaly_id)},
    )
    item = row.mappings().first()
    if item is None:
        raise HTTPException(status_code=404, detail=f"Anomaly review item {anomaly_id} not found")
    if item["status"] == "approved":
        return JSONResponse({"message": "Already acknowledged", "id": str(anomaly_id)})

    payload = dict(item["payload"] or {})
    edge_id = payload.get("contradicts_edge_id")

    if edge_id:
        await graph_service.acknowledge_edge(edge_id, db)

    await db.execute(
        text("UPDATE review_items SET status = 'approved', reviewed_at = NOW() WHERE id = :id"),
        {"id": str(anomaly_id)},
    )
    await _write_audit(
        "acknowledge_anomaly", str(anomaly_id), None,
        {"edge_id": edge_id}, db,
    )
    return JSONResponse({"acknowledged": True, "id": str(anomaly_id), "edge_id": edge_id})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/review", tags=["review"])
async def list_all_review(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _list_queue(None, page, limit, db)


@router.get("/review/dict", tags=["review"])
async def review_dict_queue(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _list_queue("dict", page, limit, db)


@router.get("/review/graph", tags=["review"])
async def review_graph_queue(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _list_queue("graph", page, limit, db)


@router.get("/review/anomalies", tags=["review"])
async def review_anomalies_queue(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _list_queue("anomaly", page, limit, db)


@router.get("/review/gaps", tags=["review"])
async def review_gaps_queue(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _list_queue("gap", page, limit, db)


@router.post("/review/{review_id}/approve", tags=["review"])
async def approve_review_item(
    review_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Approve a review item. Requires 'review' scope."""
    reviewer_id = request.headers.get("x-use-reviewer-id", "anonymous")
    now = datetime.now(timezone.utc)

    result = await db.execute(
        text("SELECT * FROM review_items WHERE id = :id"),
        {"id": review_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"review item not found: {review_id}")

    await db.execute(
        text("""
            UPDATE review_items
            SET status = 'approved', reviewer_id = :reviewer_id, reviewed_at = :now
            WHERE id = :id
        """),
        {"reviewer_id": reviewer_id, "now": now.isoformat(), "id": review_id},
    )
    await _write_audit("review_approve", review_id, reviewer_id, {"queue": row["queue"]}, db)

    updated = await db.execute(
        text("SELECT * FROM review_items WHERE id = :id"), {"id": review_id}
    )
    approved_row = _row_to_review(updated.mappings().one())

    # Kick off improvement loop in background — never blocks the response
    row_dict = _row_to_review(row)

    async def _run_improvement() -> None:
        try:
            from use.db.postgres import AsyncSessionLocal
            async with AsyncSessionLocal() as imp_db:
                async with imp_db.begin():
                    await improvement_service.route_improvement(row_dict, imp_db)
        except Exception as exc:
            logger.warning("improvement task failed for review_item=%s: %s", review_id, exc)

    asyncio.create_task(_run_improvement())

    return approved_row


@router.post("/review/{review_id}/reject", tags=["review"])
async def reject_review_item(
    review_id: str,
    body: RejectBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reject a review item. Requires 'review' scope."""
    reviewer_id = request.headers.get("x-use-reviewer-id", "anonymous")
    now = datetime.now(timezone.utc)

    result = await db.execute(
        text("SELECT * FROM review_items WHERE id = :id"),
        {"id": review_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"review item not found: {review_id}")

    await db.execute(
        text("""
            UPDATE review_items
            SET status = 'rejected', reviewer_id = :reviewer_id,
                reviewed_at = :now, notes = :notes
            WHERE id = :id
        """),
        {
            "reviewer_id": reviewer_id,
            "now": now.isoformat(),
            "notes": body.notes,
            "id": review_id,
        },
    )
    await _write_audit(
        "review_reject", review_id, reviewer_id,
        {"queue": row["queue"], "notes": body.notes}, db
    )

    updated = await db.execute(
        text("SELECT * FROM review_items WHERE id = :id"), {"id": review_id}
    )
    return _row_to_review(updated.mappings().one())


@router.put("/review/{review_id}", tags=["review"])
async def update_review_item(
    review_id: str,
    body: ReviewUpdateBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update a review item's payload and/or notes (edit+approve flow)."""
    result = await db.execute(
        text("SELECT * FROM review_items WHERE id = :id"),
        {"id": review_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"review item not found: {review_id}")

    new_payload = body.payload if body.payload is not None else row["payload"]
    new_notes = body.notes if body.notes is not None else row["notes"]

    await db.execute(
        text("""
            UPDATE review_items
            SET payload = :payload::jsonb, notes = :notes
            WHERE id = :id
        """),
        {"payload": json.dumps(new_payload), "notes": new_notes, "id": review_id},
    )

    updated = await db.execute(
        text("SELECT * FROM review_items WHERE id = :id"), {"id": review_id}
    )
    return _row_to_review(updated.mappings().one())
