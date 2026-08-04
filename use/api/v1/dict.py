from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from use.auth.dependencies import require_scope
from use.db.postgres import get_db
from use.db.redis import RedisCache, get_redis
from use.models.dict import DictEntry, OntologyEntry
from use.services.dict_service import lookup as _dict_lookup

import redis.asyncio as aioredis

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _write_audit(
    db: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: str,
    user_id: str,
    detail: dict[str, Any],
) -> None:
    await db.execute(
        text("""
            INSERT INTO audit_log (id, action, entity_type, entity_id, user_id, detail, created_at)
            VALUES (:id, :action, :entity_type, :entity_id, :user_id, :detail, NOW())
        """),
        {
            "id": str(uuid.uuid4()),
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "user_id": user_id,
            "detail": json.dumps(detail),
        },
    )


async def _write_version_snapshot(
    db: AsyncSession,
    entry_id: str,
    version: int,
    snapshot: dict[str, Any],
    reviewer_id: str | None = None,
) -> None:
    await db.execute(
        text("""
            INSERT INTO dict_versions (id, dict_entry_id, version, snapshot, created_at, reviewer_id)
            VALUES (:id, :entry_id, :version, :snapshot, NOW(), :reviewer_id)
        """),
        {
            "id": str(uuid.uuid4()),
            "entry_id": entry_id,
            "version": version,
            "snapshot": json.dumps(snapshot),
            "reviewer_id": reviewer_id,
        },
    )


async def _get_cache(raw_redis: aioredis.Redis) -> RedisCache:
    return RedisCache(client=raw_redis)


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class MergeRequest(BaseModel):
    source_id: uuid.UUID
    target_id: uuid.UUID
    reason: str


class ApproveRequest(BaseModel):
    notes: str | None = None


# ---------------------------------------------------------------------------
# Dict endpoints
# ---------------------------------------------------------------------------


@router.get("/dict/lookup", response_model=None)
async def dict_lookup(
    q: str = Query(..., min_length=1),
    domain: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    raw_redis: aioredis.Redis = Depends(get_redis),
    _user: dict = Depends(require_scope("read")),
) -> JSONResponse:
    rc = RedisCache(client=raw_redis)
    results = await _dict_lookup(q, domain, db, rc)
    return JSONResponse({
        "results": [r.__dict__ for r in results],
        "query": q,
    })


@router.get("/dict/entry/{entry_id}", response_model=None)
async def get_dict_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(require_scope("read")),
) -> JSONResponse:
    row = await db.execute(
        text("""
            SELECT id, canonical_id, term, entry_type, aliases, domain, definition,
                   source, confidence, review_status, version, created_at, updated_at
            FROM dict_entries WHERE id = :id
        """),
        {"id": str(entry_id)},
    )
    entry = row.mappings().fetchone()
    if entry is None:
        raise HTTPException(status_code=404, detail="Dict entry not found")

    versions_rows = await db.execute(
        text("""
            SELECT version, snapshot, created_at, reviewer_id
            FROM dict_versions WHERE dict_entry_id = :id ORDER BY version ASC
        """),
        {"id": str(entry_id)},
    )
    versions = [
        {
            "version": v["version"],
            "snapshot": v["snapshot"],
            "created_at": v["created_at"].isoformat() if v["created_at"] else None,
            "reviewer_id": v["reviewer_id"],
        }
        for v in versions_rows.mappings()
    ]

    aliases = entry["aliases"]
    if isinstance(aliases, str):
        try:
            aliases = json.loads(aliases)
        except Exception:
            aliases = []

    return JSONResponse({
        **{
            k: (str(entry[k]) if k in ("id",) else (entry[k].isoformat() if hasattr(entry[k], "isoformat") else entry[k]))
            for k in entry.keys()
            if k not in ("aliases",)
        },
        "aliases": aliases,
        "versions": versions,
    })


@router.post("/dict/entry", response_model=None, status_code=status.HTTP_201_CREATED)
async def create_dict_entry(
    body: DictEntry,
    db: AsyncSession = Depends(get_db),
    raw_redis: aioredis.Redis = Depends(get_redis),
    user: dict = Depends(require_scope("write")),
) -> JSONResponse:
    entry_id = str(uuid.uuid4())
    now = _now()
    aliases_json = json.dumps(body.aliases)

    await db.execute(
        text("""
            INSERT INTO dict_entries
                (id, canonical_id, term, entry_type, aliases, domain, definition,
                 source, confidence, review_status, version, created_at, updated_at)
            VALUES
                (:id, :canonical_id, :term, :entry_type, :aliases, :domain, :definition,
                 'human', 1.0, 'approved', 1, :now, :now)
        """),
        {
            "id": entry_id,
            "canonical_id": body.canonical_id,
            "term": body.term,
            "entry_type": body.entry_type,
            "aliases": aliases_json,
            "domain": body.domain,
            "definition": body.definition,
            "now": now,
        },
    )

    snapshot = body.model_dump(mode="json")
    snapshot.update({"id": entry_id, "source": "human", "confidence": 1.0,
                     "review_status": "approved", "version": 1})
    await _write_version_snapshot(db, entry_id, 1, snapshot, reviewer_id=user.get("sub"))
    await _write_audit(db, "create", "dict_entry", entry_id, user.get("sub", ""), snapshot)

    rc = RedisCache(client=raw_redis)
    await rc.invalidate_prefix("dict:lookup")

    return JSONResponse({"id": entry_id, **snapshot}, status_code=201)


@router.put("/dict/entry/{entry_id}", response_model=None)
async def update_dict_entry(
    entry_id: uuid.UUID,
    body: DictEntry,
    db: AsyncSession = Depends(get_db),
    raw_redis: aioredis.Redis = Depends(get_redis),
    user: dict = Depends(require_scope("write")),
) -> JSONResponse:
    row = await db.execute(
        text("SELECT * FROM dict_entries WHERE id = :id"),
        {"id": str(entry_id)},
    )
    existing = row.mappings().fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Dict entry not found")

    # Snapshot old state before update
    old_snapshot = dict(existing)
    new_version = existing["version"] + 1
    await _write_version_snapshot(
        db, str(entry_id), existing["version"], old_snapshot,
        reviewer_id=user.get("sub")
    )

    aliases_json = json.dumps(body.aliases)
    await db.execute(
        text("""
            UPDATE dict_entries SET
                canonical_id = :canonical_id,
                term = :term,
                entry_type = :entry_type,
                aliases = :aliases,
                domain = :domain,
                definition = :definition,
                version = :new_version,
                updated_at = NOW()
            WHERE id = :id
        """),
        {
            "id": str(entry_id),
            "canonical_id": body.canonical_id,
            "term": body.term,
            "entry_type": body.entry_type,
            "aliases": aliases_json,
            "domain": body.domain,
            "definition": body.definition,
            "new_version": new_version,
        },
    )

    new_snapshot = body.model_dump(mode="json")
    new_snapshot.update({"id": str(entry_id), "version": new_version})
    await _write_audit(db, "update", "dict_entry", str(entry_id), user.get("sub", ""), new_snapshot)

    rc = RedisCache(client=raw_redis)
    await rc.invalidate_prefix("dict:lookup")

    return JSONResponse({"id": str(entry_id), **new_snapshot})


@router.post("/dict/merge", response_model=None)
async def merge_dict_entries(
    body: MergeRequest,
    db: AsyncSession = Depends(get_db),
    raw_redis: aioredis.Redis = Depends(get_redis),
    user: dict = Depends(require_scope("admin")),
) -> JSONResponse:
    source_row = await db.execute(
        text("SELECT * FROM dict_entries WHERE id = :id"), {"id": str(body.source_id)}
    )
    source = source_row.mappings().fetchone()
    if source is None:
        raise HTTPException(status_code=404, detail="Source entry not found")

    target_row = await db.execute(
        text("SELECT * FROM dict_entries WHERE id = :id"), {"id": str(body.target_id)}
    )
    target = target_row.mappings().fetchone()
    if target is None:
        raise HTTPException(status_code=404, detail="Target entry not found")

    # Merge aliases: target.aliases ∪ source.aliases (dedup)
    source_aliases = source["aliases"]
    target_aliases = target["aliases"]
    if isinstance(source_aliases, str):
        source_aliases = json.loads(source_aliases or "[]")
    if isinstance(target_aliases, str):
        target_aliases = json.loads(target_aliases or "[]")

    merged_aliases = list(dict.fromkeys(target_aliases + source_aliases))
    merged_json = json.dumps(merged_aliases)

    await db.execute(
        text("""
            UPDATE dict_entries SET aliases = :aliases, updated_at = NOW()
            WHERE id = :id
        """),
        {"aliases": merged_json, "id": str(body.target_id)},
    )

    # Mark source as rejected
    merge_note = f"Merged into {target['canonical_id']}"
    await db.execute(
        text("""
            UPDATE dict_entries SET review_status = 'rejected', updated_at = NOW()
            WHERE id = :id
        """),
        {"id": str(body.source_id)},
    )

    # Propagate: update lakehouse_records that flagged [UNKNOWN: <source_term>]
    source_term = source["term"]
    target_canonical = target["canonical_id"]
    unknown_flag = f"[UNKNOWN: {source_term}]"
    resolved_flag = f"[RESOLVED: {target_canonical}]"

    lh_rows = await db.execute(
        text("""
            SELECT use_doc_id, md_flags FROM lakehouse_records
            WHERE md_flags::text LIKE :pattern
        """),
        {"pattern": f"%{unknown_flag}%"},
    )
    for lh in lh_rows.mappings():
        flags = lh["md_flags"]
        if isinstance(flags, str):
            flags = json.loads(flags)
        updated = [f.replace(unknown_flag, resolved_flag) for f in flags]
        await db.execute(
            text("UPDATE lakehouse_records SET md_flags = :flags WHERE use_doc_id = :id"),
            {"flags": json.dumps(updated), "id": str(lh["use_doc_id"])},
        )

    await _write_audit(
        db, "merge", "dict_entry", str(body.source_id), user.get("sub", ""),
        {"source_id": str(body.source_id), "target_id": str(body.target_id), "reason": body.reason},
    )

    rc = RedisCache(client=raw_redis)
    await rc.invalidate_prefix("dict:lookup")

    return JSONResponse({
        "merged": str(body.source_id),
        "into": str(body.target_id),
        "target_canonical_id": target_canonical,
    })


@router.get("/dict/pending", response_model=None)
async def list_pending_dict(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(require_scope("review")),
) -> JSONResponse:
    rows = await db.execute(
        text("""
            SELECT r.id, r.queue, r.status, r.payload, r.created_at, r.notes,
                   d.term, d.canonical_id, d.review_status AS entry_status
            FROM review_items r
            LEFT JOIN dict_entries d ON d.id = r.dict_entry_id
            WHERE r.queue = 'dict' AND r.status = 'pending'
            ORDER BY r.created_at DESC
        """)
    )
    items = []
    for row in rows.mappings():
        items.append({
            "id": str(row["id"]),
            "queue": row["queue"],
            "status": row["status"],
            "payload": row["payload"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "notes": row["notes"],
            "term": row["term"],
            "canonical_id": row["canonical_id"],
            "entry_status": row["entry_status"],
        })
    return JSONResponse({"items": items, "count": len(items)})


@router.post("/dict/approve/{review_id}", response_model=None)
async def approve_dict_entry(
    review_id: uuid.UUID,
    body: ApproveRequest,
    db: AsyncSession = Depends(get_db),
    raw_redis: aioredis.Redis = Depends(get_redis),
    user: dict = Depends(require_scope("review")),
) -> JSONResponse:
    row = await db.execute(
        text("SELECT * FROM review_items WHERE id = :id"), {"id": str(review_id)}
    )
    review = row.mappings().fetchone()
    if review is None:
        raise HTTPException(status_code=404, detail="Review item not found")

    entry_id = review["dict_entry_id"]
    if entry_id is None:
        raise HTTPException(status_code=422, detail="Review item has no linked dict_entry_id")

    # Fetch entry for propagation
    entry_row = await db.execute(
        text("SELECT * FROM dict_entries WHERE id = :id"), {"id": str(entry_id)}
    )
    entry = entry_row.mappings().fetchone()
    if entry is None:
        raise HTTPException(status_code=404, detail="Dict entry not found")

    # Approve: set status + confidence on dict_entry
    new_version = entry["version"] + 1
    await _write_version_snapshot(db, str(entry_id), entry["version"], dict(entry),
                                   reviewer_id=user.get("sub"))
    await db.execute(
        text("""
            UPDATE dict_entries SET
                review_status = 'approved',
                confidence = 1.0,
                version = :version,
                updated_at = NOW()
            WHERE id = :id
        """),
        {"version": new_version, "id": str(entry_id)},
    )

    # Update review_item
    await db.execute(
        text("""
            UPDATE review_items SET
                status = 'approved',
                reviewed_at = NOW(),
                reviewer_id = :reviewer_id,
                notes = :notes
            WHERE id = :id
        """),
        {
            "reviewer_id": user.get("sub", ""),
            "notes": body.notes,
            "id": str(review_id),
        },
    )

    # Propagate: resolve [UNKNOWN: <term>] flags in lakehouse_records
    term = entry["term"]
    aliases_raw = entry["aliases"]
    if isinstance(aliases_raw, str):
        aliases_raw = json.loads(aliases_raw or "[]")
    all_terms = [term] + (aliases_raw or [])
    canonical_id = entry["canonical_id"]

    for t in all_terms:
        unknown_flag = f"[UNKNOWN: {t}]"
        resolved_flag = f"[RESOLVED: {canonical_id}]"
        lh_rows = await db.execute(
            text("""
                SELECT use_doc_id, md_flags FROM lakehouse_records
                WHERE md_flags::text LIKE :pattern
            """),
            {"pattern": f"%{unknown_flag}%"},
        )
        for lh in lh_rows.mappings():
            flags = lh["md_flags"]
            if isinstance(flags, str):
                flags = json.loads(flags)
            updated = [f.replace(unknown_flag, resolved_flag) for f in flags]
            await db.execute(
                text("UPDATE lakehouse_records SET md_flags = :flags WHERE use_doc_id = :id"),
                {"flags": json.dumps(updated), "id": str(lh["use_doc_id"])},
            )

    await _write_audit(
        db, "approve", "dict_entry", str(entry_id), user.get("sub", ""),
        {"review_id": str(review_id), "notes": body.notes},
    )

    rc = RedisCache(client=raw_redis)
    await rc.invalidate_prefix("dict:lookup")

    return JSONResponse({
        "approved": str(entry_id),
        "canonical_id": canonical_id,
        "review_id": str(review_id),
    })


# ---------------------------------------------------------------------------
# Ontology endpoints
# ---------------------------------------------------------------------------


@router.get("/ontology", response_model=None)
async def list_ontology(
    domain: str | None = Query(default=None),
    ontology_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(require_scope("read")),
) -> JSONResponse:
    filters = []
    params: dict[str, Any] = {}
    if domain:
        filters.append("domain = :domain")
        params["domain"] = domain
    if ontology_type:
        filters.append("ontology_type = :ontology_type")
        params["ontology_type"] = ontology_type

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    rows = await db.execute(
        text(f"""
            SELECT id, ontology_type, name, description, domain,
                   source, confidence, version, created_at
            FROM ontology_entries {where}
            ORDER BY name ASC
        """),
        params,
    )
    entries = [
        {
            **{k: (str(r[k]) if k == "id" else (r[k].isoformat() if hasattr(r[k], "isoformat") else r[k]))
               for k in r.keys()}
        }
        for r in rows.mappings()
    ]
    return JSONResponse({"entries": entries, "count": len(entries)})


@router.post("/ontology/entry", response_model=None, status_code=status.HTTP_201_CREATED)
async def create_ontology_entry(
    body: OntologyEntry,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_scope("write")),
) -> JSONResponse:
    entry_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO ontology_entries
                (id, ontology_type, name, description, domain, source, confidence, version, created_at)
            VALUES
                (:id, :ontology_type, :name, :description, :domain, 'human', 1.0, 1, NOW())
        """),
        {
            "id": entry_id,
            "ontology_type": body.ontology_type,
            "name": body.name,
            "description": body.description,
            "domain": body.domain,
        },
    )
    snapshot = body.model_dump(mode="json")
    snapshot.update({"id": entry_id, "source": "human", "confidence": 1.0})
    await _write_audit(db, "create", "ontology_entry", entry_id, user.get("sub", ""), snapshot)

    return JSONResponse({"id": entry_id, **snapshot}, status_code=201)
