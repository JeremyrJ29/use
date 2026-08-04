from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from use.models.catalog import CatalogEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_entry(row: Any) -> CatalogEntry:
    """Convert a SQLAlchemy Row (mapping) to a CatalogEntry Pydantic model."""
    return CatalogEntry(
        id=row.id,
        canonical_id=row.canonical_id,
        entity_type=row.entity_type,
        display_name=row.display_name,
        aliases=row.aliases if isinstance(row.aliases, list) else json.loads(row.aliases or "[]"),
        source_ids=row.source_ids if isinstance(row.source_ids, list) else json.loads(row.source_ids or "[]"),
        document_ids=row.document_ids if isinstance(row.document_ids, list) else json.loads(row.document_ids or "[]"),
        first_seen=row.first_seen,
        last_seen=row.last_seen,
        occurrence_count=row.occurrence_count,
        confidence=row.confidence,
        confirmed=row.confirmed,
        notes=row.notes,
    )


async def _write_audit(
    action: str,
    entity_id: str,
    user_id: str | None,
    detail: dict,
    db: AsyncSession,
) -> None:
    await db.execute(
        text("""
            INSERT INTO audit_log (id, action, entity_type, entity_id, user_id, detail, created_at)
            VALUES (:id, :action, 'catalog_entry', :entity_id, :user_id, :detail, NOW())
        """),
        {
            "id": str(uuid.uuid4()),
            "action": action,
            "entity_id": entity_id,
            "user_id": user_id,
            "detail": json.dumps(detail),
        },
    )


# ---------------------------------------------------------------------------
# Public async functions
# ---------------------------------------------------------------------------


async def upsert_entity(
    canonical_id: str,
    entity_type: str,
    display_name: str,
    aliases: list[str],
    source_id: str,
    document_id: str,
    confidence: float,
    db: AsyncSession,
) -> CatalogEntry:
    """
    Idempotent upsert of a catalog entry.

    - If the entry exists: increment occurrence_count, update last_seen,
      merge document_id / source_id / aliases (no duplicates), compute
      running-average confidence.
    - If it does not exist: INSERT new entry.
    - When a new entry is created with confirmed=False and confidence < 0.7,
      auto-queue a review_item with queue='ontology'.
    """
    now = datetime.now(timezone.utc)

    # Attempt INSERT first (ON CONFLICT updates)
    await db.execute(
        text("""
            INSERT INTO catalog_entries
                (id, canonical_id, entity_type, display_name, aliases,
                 source_ids, document_ids, first_seen, last_seen,
                 occurrence_count, confidence, confirmed, notes)
            VALUES
                (gen_random_uuid(), :canonical_id, :entity_type, :display_name,
                 :aliases::jsonb, :source_ids::jsonb, :document_ids::jsonb,
                 :now, :now, 1, :confidence, FALSE, NULL)
            ON CONFLICT (canonical_id) DO UPDATE SET
                occurrence_count = catalog_entries.occurrence_count + 1,
                last_seen        = :now,
                confidence       = (
                    catalog_entries.confidence * catalog_entries.occurrence_count
                    + :confidence
                ) / (catalog_entries.occurrence_count + 1),
                document_ids     = (
                    SELECT jsonb_agg(DISTINCT elem)
                    FROM jsonb_array_elements_text(
                        catalog_entries.document_ids || :document_ids::jsonb
                    ) elem
                ),
                source_ids       = (
                    SELECT jsonb_agg(DISTINCT elem)
                    FROM jsonb_array_elements_text(
                        catalog_entries.source_ids || :source_ids::jsonb
                    ) elem
                ),
                aliases          = (
                    SELECT jsonb_agg(DISTINCT elem)
                    FROM jsonb_array_elements_text(
                        catalog_entries.aliases || :aliases::jsonb
                    ) elem
                )
        """),
        {
            "canonical_id": canonical_id,
            "entity_type": entity_type,
            "display_name": display_name,
            "aliases": json.dumps(list({*aliases})),
            "source_ids": json.dumps([source_id]),
            "document_ids": json.dumps([document_id]),
            "confidence": confidence,
            "now": now.isoformat(),
        },
    )

    # Fetch the upserted row
    result = await db.execute(
        text("SELECT * FROM catalog_entries WHERE canonical_id = :cid"),
        {"cid": canonical_id},
    )
    row = result.mappings().one()
    entry = _row_to_entry(row)

    # Auto-queue review for new low-confidence entries
    if not entry.confirmed and entry.confidence < 0.7 and entry.occurrence_count == 1:
        await db.execute(
            text("""
                INSERT INTO review_items (id, queue, status, payload, created_at)
                VALUES (:id, 'ontology', 'pending', :payload::jsonb, NOW())
            """),
            {
                "id": str(uuid.uuid4()),
                "payload": json.dumps({
                    "canonical_id": canonical_id,
                    "display_name": display_name,
                    "entity_type": entity_type,
                    "source_id": source_id,
                    "occurrence_count": 1,
                }),
            },
        )
        logger.debug("catalog_service: queued ontology review for %s", canonical_id)

    await _write_audit(
        action="catalog_upsert",
        entity_id=canonical_id,
        user_id=source_id,
        detail={"document_id": document_id, "confidence": confidence},
        db=db,
    )

    return entry


async def get_entity(canonical_id: str, db: AsyncSession) -> CatalogEntry | None:
    """Return a single catalog entry by canonical_id, or None if not found."""
    result = await db.execute(
        text("SELECT * FROM catalog_entries WHERE canonical_id = :cid"),
        {"cid": canonical_id},
    )
    row = result.mappings().one_or_none()
    return _row_to_entry(row) if row else None


async def search_entities(
    q: str,
    db: AsyncSession,
    limit: int = 20,
) -> list[CatalogEntry]:
    """
    Trigram + ILIKE search on display_name and aliases JSONB array.
    Orders by occurrence_count DESC then confidence DESC.
    """
    pattern = f"%{q}%"
    result = await db.execute(
        text("""
            SELECT * FROM catalog_entries
            WHERE display_name ILIKE :pattern
               OR EXISTS (
                   SELECT 1 FROM jsonb_array_elements_text(aliases) alias
                   WHERE alias ILIKE :pattern
               )
            ORDER BY occurrence_count DESC, confidence DESC
            LIMIT :limit
        """),
        {"pattern": pattern, "limit": limit},
    )
    return [_row_to_entry(r) for r in result.mappings().all()]


async def get_entity_documents(
    canonical_id: str,
    db: AsyncSession,
) -> list[dict]:
    """
    Return lakehouse record summaries for documents that reference this entity.
    Uses JSONB containment: md_tags @> '["entity:<canonical_id>"]'
    """
    tag = f"entity:{canonical_id}"
    result = await db.execute(
        text("""
            SELECT use_doc_id, source_id, created_at, version,
                   md_word_count, md_tags, md_flags
            FROM lakehouse_records
            WHERE md_tags @> :tag_json::jsonb
            ORDER BY created_at DESC
        """),
        {"tag_json": json.dumps([tag])},
    )
    rows = result.mappings().all()
    return [
        {
            "use_doc_id": str(r["use_doc_id"]),
            "source_id": r["source_id"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "version": r["version"],
            "md_word_count": r["md_word_count"],
            "md_tags": r["md_tags"],
            "md_flags": r["md_flags"],
        }
        for r in rows
    ]


async def get_entity_relationships(
    canonical_id: str,
    db: AsyncSession,
) -> list[dict]:
    """
    Parse ## Relationships sections from md_content of documents that tag this entity.
    Returns list of {subject, predicate, object, source_doc_id}.
    """
    tag = f"entity:{canonical_id}"
    result = await db.execute(
        text("""
            SELECT use_doc_id, source_id, md_content
            FROM lakehouse_records
            WHERE md_tags @> :tag_json::jsonb
              AND md_content IS NOT NULL
        """),
        {"tag_json": json.dumps([tag])},
    )
    rows = result.mappings().all()

    relationships: list[dict] = []
    for row in rows:
        content: str = row["md_content"] or ""
        in_rel_section = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "## Relationships":
                in_rel_section = True
                continue
            if in_rel_section and stripped.startswith("##"):
                break
            if in_rel_section and stripped.startswith("-"):
                # Format: "- subject → predicate → object"
                parts = stripped.lstrip("- ").split(" → ")
                if len(parts) == 3:
                    relationships.append({
                        "subject": parts[0].strip(),
                        "predicate": parts[1].strip(),
                        "object": parts[2].strip(),
                        "source_doc_id": str(row["use_doc_id"]),
                    })

    return relationships


async def confirm_entity(
    canonical_id: str,
    reviewer_id: str,
    db: AsyncSession,
) -> CatalogEntry:
    """Set confirmed=True for a catalog entry and write an audit log entry."""
    await db.execute(
        text("""
            UPDATE catalog_entries
            SET confirmed = TRUE
            WHERE canonical_id = :cid
        """),
        {"cid": canonical_id},
    )
    await _write_audit(
        action="catalog_confirm",
        entity_id=canonical_id,
        user_id=reviewer_id,
        detail={"reviewer_id": reviewer_id},
        db=db,
    )
    entry = await get_entity(canonical_id, db)
    if entry is None:
        raise ValueError(f"catalog entry not found: {canonical_id}")
    return entry


async def compute_catalog_stats(db: AsyncSession) -> dict:
    """Return aggregate statistics about the catalog."""
    totals = await db.execute(
        text("""
            SELECT
                COUNT(*)                                    AS total_entities,
                COUNT(*) FILTER (WHERE confirmed = TRUE)    AS confirmed_count,
                COUNT(*) FILTER (WHERE confirmed = FALSE)   AS unconfirmed_count
            FROM catalog_entries
        """)
    )
    t = totals.mappings().one()

    top10 = await db.execute(
        text("""
            SELECT canonical_id, occurrence_count
            FROM catalog_entries
            ORDER BY occurrence_count DESC
            LIMIT 10
        """)
    )

    breakdown = await db.execute(
        text("""
            SELECT entity_type, COUNT(*) AS cnt
            FROM catalog_entries
            GROUP BY entity_type
        """)
    )

    return {
        "total_entities": t["total_entities"],
        "confirmed_count": t["confirmed_count"],
        "unconfirmed_count": t["unconfirmed_count"],
        "most_observed": [
            {"canonical_id": r["canonical_id"], "occurrence_count": r["occurrence_count"]}
            for r in top10.mappings().all()
        ],
        "entity_type_breakdown": {
            r["entity_type"]: r["cnt"]
            for r in breakdown.mappings().all()
        },
    }


# ---------------------------------------------------------------------------
# Legacy class shim (Phase 0 compatibility)
# ---------------------------------------------------------------------------


class CatalogService:
    """Thin backward-compat wrapper. New code should call module-level functions."""

    async def extract_entities(self, record):  # type: ignore[override]
        return []

    async def cross_reference(self, entry):  # type: ignore[override]
        return []

    async def update_occurrence(self, canonical_id: str) -> None:
        pass

    async def confirm_entry(self, canonical_id: str, reviewer_id: str) -> CatalogEntry | None:
        return None
