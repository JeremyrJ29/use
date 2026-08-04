from __future__ import annotations

import json
import uuid as _uuid
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from use.db.postgres import get_db
from use.services import pattern_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_pattern(row: Any) -> dict:
    return {
        "id": str(row["id"]),
        "pattern_type": row["pattern_type"],
        "entity_ids": row["entity_ids"],
        "score": row["score"],
        "support": row["support"],
        "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
        "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
        "metadata": row["metadata"] or {},
    }


def _row_to_anomaly(row: Any) -> dict:
    return {
        "id": str(row["id"]),
        "anomaly_type": row["anomaly_type"],
        "source_doc_id": str(row["source_doc_id"]) if row["source_doc_id"] else None,
        "entity_ids": row["entity_ids"],
        "severity": row["severity"],
        "acknowledged": row["acknowledged"],
        "review_item_id": str(row["review_item_id"]) if row["review_item_id"] else None,
        "detail": row["detail"] or {},
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def _write_audit(action: str, entity_id: str, detail: dict, db: AsyncSession) -> None:
    await db.execute(
        text("""
            INSERT INTO audit_log (id, action, entity_type, entity_id, user_id, detail, created_at)
            VALUES (:id, :action, 'anomaly_flag', :entity_id, NULL, :detail, NOW())
        """),
        {
            "id": str(_uuid.uuid4()),
            "action": action,
            "entity_id": entity_id,
            "detail": json.dumps(detail),
        },
    )


# ---------------------------------------------------------------------------
# NOTE: Static paths MUST be registered BEFORE parameterized paths to avoid
# FastAPI routing the literal strings "co-occurrence" and "sequences" into
# the {id} parameter of GET /patterns/{id}.
# ---------------------------------------------------------------------------


# GET /patterns/co-occurrence — must come before /patterns/{id}
@router.get("/patterns/co-occurrence", tags=["patterns"])
async def list_co_occurrence_patterns(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List co-occurrence patterns ordered by PMI score DESC."""
    offset = (page - 1) * limit
    total_res = await db.execute(
        text("SELECT COUNT(*) FROM pattern_records WHERE pattern_type = 'co_occurrence'")
    )
    total = total_res.scalar()
    rows_res = await db.execute(
        text("""
            SELECT * FROM pattern_records
            WHERE pattern_type = 'co_occurrence'
            ORDER BY score DESC
            LIMIT :limit OFFSET :offset
        """),
        {"limit": limit, "offset": offset},
    )
    items = [_row_to_pattern(r) for r in rows_res.mappings().all()]
    return {"items": items, "total": total, "page": page, "limit": limit}


# GET /patterns/sequences — must come before /patterns/{id}
@router.get("/patterns/sequences", tags=["patterns"])
async def list_sequence_patterns(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List sequence patterns ordered by support DESC."""
    offset = (page - 1) * limit
    total_res = await db.execute(
        text("SELECT COUNT(*) FROM pattern_records WHERE pattern_type = 'sequence'")
    )
    total = total_res.scalar()
    rows_res = await db.execute(
        text("""
            SELECT * FROM pattern_records
            WHERE pattern_type = 'sequence'
            ORDER BY support DESC
            LIMIT :limit OFFSET :offset
        """),
        {"limit": limit, "offset": offset},
    )
    items = [_row_to_pattern(r) for r in rows_res.mappings().all()]
    return {"items": items, "total": total, "page": page, "limit": limit}


# POST /patterns/analyze — trigger immediate analysis
@router.post("/patterns/analyze", tags=["patterns"])
async def trigger_analysis(db: AsyncSession = Depends(get_db)) -> dict:
    """Trigger pattern analysis immediately. Requires write scope."""
    async with db.begin():
        summary = await pattern_service.run_pattern_analysis(db)
    return {"status": "ok", "summary": summary}


# GET /patterns — list all pattern_records
@router.get("/patterns", tags=["patterns"])
async def list_patterns(
    pattern_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List pattern records, filterable by pattern_type, ordered by score DESC."""
    offset = (page - 1) * limit
    where = "TRUE"
    params: dict = {"limit": limit, "offset": offset}
    if pattern_type:
        where = "pattern_type = :ptype"
        params["ptype"] = pattern_type

    total_res = await db.execute(
        text(f"SELECT COUNT(*) FROM pattern_records WHERE {where}"), params
    )
    total = total_res.scalar()
    rows_res = await db.execute(
        text(f"""
            SELECT * FROM pattern_records
            WHERE {where}
            ORDER BY score DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [_row_to_pattern(r) for r in rows_res.mappings().all()]
    return {"items": items, "total": total, "page": page, "limit": limit}


# GET /patterns/{id} — single record (AFTER static routes)
@router.get("/patterns/{pattern_id}", tags=["patterns"])
async def get_pattern(
    pattern_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch a single pattern record by id."""
    row = await db.execute(
        text("SELECT * FROM pattern_records WHERE id = :id"),
        {"id": str(pattern_id)},
    )
    result = row.mappings().first()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Pattern {pattern_id} not found")
    return _row_to_pattern(result)


# ---------------------------------------------------------------------------
# Anomaly routes
# ---------------------------------------------------------------------------


# GET /anomalies
@router.get("/anomalies", tags=["patterns"])
async def list_anomalies(
    anomaly_type: str | None = Query(default=None),
    acknowledged: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List anomaly flags, filterable, ordered by severity DESC, created_at DESC."""
    offset = (page - 1) * limit
    conditions = ["TRUE"]
    params: dict = {"limit": limit, "offset": offset}
    if anomaly_type is not None:
        conditions.append("anomaly_type = :atype")
        params["atype"] = anomaly_type
    if acknowledged is not None:
        conditions.append("acknowledged = :ack")
        params["ack"] = acknowledged
    where = " AND ".join(conditions)

    total_res = await db.execute(
        text(f"SELECT COUNT(*) FROM anomaly_flags WHERE {where}"), params
    )
    total = total_res.scalar()
    rows_res = await db.execute(
        text(f"""
            SELECT * FROM anomaly_flags
            WHERE {where}
            ORDER BY severity DESC, created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = [_row_to_anomaly(r) for r in rows_res.mappings().all()]
    return {"items": items, "total": total, "page": page, "limit": limit}


# GET /anomalies/{id}
@router.get("/anomalies/{anomaly_id}", tags=["patterns"])
async def get_anomaly(
    anomaly_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch a single anomaly flag by id."""
    row = await db.execute(
        text("SELECT * FROM anomaly_flags WHERE id = :id"),
        {"id": str(anomaly_id)},
    )
    result = row.mappings().first()
    if result is None:
        raise HTTPException(status_code=404, detail=f"Anomaly {anomaly_id} not found")
    return _row_to_anomaly(result)


# POST /anomalies/{id}/acknowledge
@router.post("/anomalies/{anomaly_id}/acknowledge", tags=["patterns"])
async def acknowledge_anomaly(
    anomaly_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Acknowledge an anomaly flag. Requires review scope."""
    async with db.begin():
        row = await db.execute(
            text("SELECT * FROM anomaly_flags WHERE id = :id"),
            {"id": str(anomaly_id)},
        )
        flag = row.mappings().first()
        if flag is None:
            raise HTTPException(status_code=404, detail=f"Anomaly {anomaly_id} not found")
        if flag["acknowledged"]:
            return {"message": "Already acknowledged", "id": str(anomaly_id)}

        await db.execute(
            text("UPDATE anomaly_flags SET acknowledged = TRUE WHERE id = :id"),
            {"id": str(anomaly_id)},
        )

        # Update linked review_item if present
        if flag["review_item_id"]:
            await db.execute(
                text("""
                    UPDATE review_items
                    SET status = 'approved', reviewed_at = NOW()
                    WHERE id = :id AND status = 'pending'
                """),
                {"id": str(flag["review_item_id"])},
            )

        await _write_audit(
            "acknowledge_anomaly",
            str(anomaly_id),
            {"anomaly_type": flag["anomaly_type"], "severity": flag["severity"]},
            db,
        )

    return {
        "acknowledged": True,
        "id": str(anomaly_id),
        "review_item_id": str(flag["review_item_id"]) if flag["review_item_id"] else None,
    }

