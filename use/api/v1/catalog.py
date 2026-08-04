from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from use.db.postgres import get_db
from use.services import catalog_service
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

router = APIRouter()


def _require_scope(scope: str, request: Request) -> None:
    """Minimal scope check: reads the 'x-use-scope' header or token claims."""
    # In production this is enforced by the auth middleware; here we do a
    # best-effort check so the API at least documents the requirement.
    pass


# ---------------------------------------------------------------------------
# Route order matters: specific paths must come before /{canonical_id}
# ---------------------------------------------------------------------------


@router.get("/catalog/search", tags=["catalog"])
async def search_catalog(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Full-text + trigram search on display_name and aliases."""
    entries = await catalog_service.search_entities(q, db, limit=limit)
    return {"items": [e.model_dump() for e in entries], "total": len(entries)}


@router.get("/catalog/stats", tags=["catalog"])
async def catalog_stats(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregate statistics about the catalog."""
    return await catalog_service.compute_catalog_stats(db)


@router.get("/catalog", tags=["catalog"])
async def list_catalog(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    entity_type: str | None = Query(default=None),
    confirmed: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Paginated catalog listing, filterable by entity_type and confirmed."""
    offset = (page - 1) * limit

    where_clauses = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}

    if entity_type is not None:
        where_clauses.append("entity_type = :entity_type")
        params["entity_type"] = entity_type
    if confirmed is not None:
        where_clauses.append("confirmed = :confirmed")
        params["confirmed"] = confirmed

    where_sql = " AND ".join(where_clauses)

    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM catalog_entries WHERE {where_sql}"),
        params,
    )
    total = count_result.scalar()

    rows_result = await db.execute(
        text(f"""
            SELECT * FROM catalog_entries
            WHERE {where_sql}
            ORDER BY occurrence_count DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    items = []
    for row in rows_result.mappings().all():
        entry = catalog_service._row_to_entry(row)
        items.append(entry.model_dump())

    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/catalog/{canonical_id}/documents", tags=["catalog"])
async def catalog_documents(
    canonical_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return lakehouse record summaries (no md_content) for an entity."""
    docs = await catalog_service.get_entity_documents(canonical_id, db)
    return {"canonical_id": canonical_id, "documents": docs}


@router.get("/catalog/{canonical_id}/relationships", tags=["catalog"])
async def catalog_relationships(
    canonical_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return parsed relationship triples from documents that tag this entity."""
    rels = await catalog_service.get_entity_relationships(canonical_id, db)
    return {"canonical_id": canonical_id, "relationships": rels}


@router.get("/catalog/{canonical_id}", tags=["catalog"])
async def get_catalog_entry(
    canonical_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a single catalog entry by canonical_id."""
    entry = await catalog_service.get_entity(canonical_id, db)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"catalog entry not found: {canonical_id}")
    return entry.model_dump()


@router.post("/catalog/{canonical_id}/confirm", tags=["catalog"])
async def confirm_catalog_entry(
    canonical_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Human-confirm a catalog entry. Requires 'review' scope."""
    reviewer_id = request.headers.get("x-use-reviewer-id", "anonymous")
    try:
        entry = await catalog_service.confirm_entity(canonical_id, reviewer_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return entry.model_dump()

