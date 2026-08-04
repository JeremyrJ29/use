"""Documents REST endpoints — list, retrieve, and full-text search lakehouse records."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from use.db.postgres import get_db

router = APIRouter()


@router.get("/documents")
async def list_documents(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a paginated list of lakehouse record summaries (no md_content)."""
    offset = (page - 1) * limit
    rows = await db.execute(
        text("""
            SELECT use_doc_id, ingestion_record_id, source_id, created_at,
                   version, md_word_count, md_tags, md_flags
            FROM lakehouse_records
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"limit": limit, "offset": offset},
    )
    count_row = await db.execute(text("SELECT COUNT(*) FROM lakehouse_records"))
    total = count_row.scalar() or 0

    items = [
        {
            "use_doc_id": str(r[0]),
            "ingestion_record_id": str(r[1]),
            "source_id": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "version": r[4],
            "word_count": r[5],
            "tags": r[6],
            "flags": r[7],
        }
        for r in rows.fetchall()
    ]
    return {"total": total, "page": page, "limit": limit, "items": items}


@router.get("/documents/search")
async def search_documents(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Full-text search over md_content using Postgres tsvector / ts_rank."""
    rows = await db.execute(
        text("""
            SELECT use_doc_id, source_id, created_at, version, md_word_count,
                   ts_rank(md_content_tsv, plainto_tsquery('english', :q)) AS rank
            FROM lakehouse_records
            WHERE md_content_tsv @@ plainto_tsquery('english', :q)
            ORDER BY rank DESC
            LIMIT :limit
        """),
        {"q": q, "limit": limit},
    )
    results = [
        {
            "use_doc_id": str(r[0]),
            "source_id": r[1],
            "created_at": r[2].isoformat() if r[2] else None,
            "version": r[3],
            "word_count": r[4],
            "rank": float(r[5]),
        }
        for r in rows.fetchall()
    ]
    return {"query": q, "results": results}


@router.get("/documents/{doc_id}")
async def get_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the full lakehouse record including md_content."""
    row = await db.execute(
        text("""
            SELECT use_doc_id, ingestion_record_id, source_id, created_at,
                   version, md_content, md_word_count, md_tags, md_flags,
                   graph_node_ids, graph_edge_ids
            FROM lakehouse_records
            WHERE use_doc_id = :doc_id
        """),
        {"doc_id": str(doc_id)},
    )
    r = row.fetchone()
    if r is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "use_doc_id": str(r[0]),
        "ingestion_record_id": str(r[1]),
        "source_id": r[2],
        "created_at": r[3].isoformat() if r[3] else None,
        "version": r[4],
        "md_content": r[5],
        "word_count": r[6],
        "tags": r[7],
        "flags": r[8],
        "graph_node_ids": r[9],
        "graph_edge_ids": r[10],
    }

