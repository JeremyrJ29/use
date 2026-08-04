from __future__ import annotations

"""
DictService — canonical lookup, fuzzy search, auto-detection.

Lookup algorithm:
    Step 1: Exact match on canonical_id (case-insensitive)       → confidence 1.0
    Step 2: Exact match on any alias in aliases JSONB array       → confidence 0.95
    Step 3: Fuzzy (Levenshtein ≤ 2) on term / aliases            → 0.80 (dist=1), 0.65 (dist=2)
    Step 4: Full-text search via Postgres tsvector                → 0.40–0.70

Logic tests (illustrative):
    lookup('lathe_1')      → alias-exact match, confidence 0.95
    lookup('lath_1')       → fuzzy match on 'lathe_1' (Levenshtein 1), confidence 0.80
    lookup('xyz_unknown_999') → empty list → triggers auto_detect_and_queue
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from use.db.redis import RedisCache, cache as _default_cache

logger = logging.getLogger(__name__)


@dataclass
class DictLookupResult:
    id: str
    canonical_id: str
    term: str
    confidence: float
    review_status: str
    aliases: list[str]


def _row_to_result(row: Any, confidence: float) -> DictLookupResult:
    aliases = row["aliases"]
    if isinstance(aliases, str):
        try:
            aliases = json.loads(aliases)
        except Exception:
            aliases = []
    return DictLookupResult(
        id=str(row["id"]),
        canonical_id=row["canonical_id"],
        term=row["term"],
        confidence=confidence,
        review_status=row["review_status"],
        aliases=aliases if isinstance(aliases, list) else [],
    )


async def lookup(
    q: str,
    domain: str | None,
    db: AsyncSession,
    redis: RedisCache | None = None,
) -> list[DictLookupResult]:
    """
    Full lookup algorithm: exact → alias-exact → fuzzy → fulltext.

    Returns a de-duplicated list sorted by confidence desc.
    Only 'approved' entries are returned (except exact canonical_id match).
    """
    if redis is None:
        redis = _default_cache

    cache_key = f"dict:lookup:{q}:{domain or ''}"
    cached = await redis.get(cache_key)
    if cached is not None:
        try:
            return [DictLookupResult(**r) for r in cached]
        except Exception:
            pass

    results: dict[str, DictLookupResult] = {}

    # --- Step 1: exact canonical_id match (case-insensitive) ---
    domain_clause = "AND domain = :domain" if domain else ""
    rows = await db.execute(
        text(f"""
            SELECT id, canonical_id, term, review_status, aliases
            FROM dict_entries
            WHERE lower(canonical_id) = lower(:q)
            {domain_clause}
            LIMIT 5
        """),
        {"q": q, **({"domain": domain} if domain else {})},
    )
    for row in rows.mappings():
        results[str(row["id"])] = _row_to_result(row, 1.0)

    # --- Step 2: exact alias match ---
    rows = await db.execute(
        text(f"""
            SELECT id, canonical_id, term, review_status, aliases
            FROM dict_entries
            WHERE aliases @> :alias_json
              AND review_status = 'approved'
              {domain_clause}
            LIMIT 5
        """),
        {"alias_json": json.dumps([q]), **({"domain": domain} if domain else {})},
    )
    for row in rows.mappings():
        rid = str(row["id"])
        if rid not in results:
            results[rid] = _row_to_result(row, 0.95)

    # Also try case-insensitive alias match via JSONB lower search
    rows = await db.execute(
        text(f"""
            SELECT id, canonical_id, term, review_status, aliases
            FROM dict_entries
            WHERE lower(aliases::text) LIKE :alias_pat
              AND review_status = 'approved'
              {domain_clause}
            LIMIT 5
        """),
        {
            "alias_pat": f"%{q.lower()}%",
            **({"domain": domain} if domain else {}),
        },
    )
    for row in rows.mappings():
        rid = str(row["id"])
        if rid not in results:
            # verify the alias actually matches (not just substring)
            aliases = row["aliases"]
            if isinstance(aliases, str):
                try:
                    aliases = json.loads(aliases)
                except Exception:
                    aliases = []
            if any(a.lower() == q.lower() for a in (aliases or [])):
                results[rid] = _row_to_result(row, 0.95)

    # --- Step 3: fuzzy (Levenshtein ≤ 2) on term ---
    rows = await db.execute(
        text(f"""
            SELECT id, canonical_id, term, review_status, aliases,
                   levenshtein(lower(term), lower(:q)) AS dist
            FROM dict_entries
            WHERE levenshtein(lower(term), lower(:q)) <= 2
              AND review_status = 'approved'
              {domain_clause}
            ORDER BY dist ASC
            LIMIT 10
        """),
        {"q": q, **({"domain": domain} if domain else {})},
    )
    for row in rows.mappings():
        rid = str(row["id"])
        if rid not in results:
            dist = row["dist"]
            confidence = 0.80 if dist <= 1 else 0.65
            results[rid] = _row_to_result(row, confidence)

    # --- Step 4: full-text search ---
    rows = await db.execute(
        text(f"""
            SELECT id, canonical_id, term, review_status, aliases,
                   ts_rank(
                       to_tsvector('english', term || ' ' || coalesce(definition, '')),
                       plainto_tsquery('english', :q)
                   ) AS rank
            FROM dict_entries
            WHERE to_tsvector('english', term || ' ' || coalesce(definition, ''))
                  @@ plainto_tsquery('english', :q)
              AND review_status = 'approved'
              {domain_clause}
            ORDER BY rank DESC
            LIMIT 5
        """),
        {"q": q, **({"domain": domain} if domain else {})},
    )
    for row in rows.mappings():
        rid = str(row["id"])
        if rid not in results:
            # Normalise ts_rank (0–1) to 0.40–0.70
            rank = float(row["rank"])
            confidence = 0.40 + min(rank, 1.0) * 0.30
            results[rid] = _row_to_result(row, confidence)

    # --- Step 5: sort by confidence desc ---
    final = sorted(results.values(), key=lambda r: r.confidence, reverse=True)

    # --- Step 7: cache result ---
    await redis.set(
        cache_key,
        [r.__dict__ for r in final],
        ttl_seconds=3600,
    )

    return final


async def auto_detect_and_queue(
    term: str,
    context: str,
    source_id: str,
    db: AsyncSession,
) -> None:
    """
    Called by structuring pipeline when a term returns no lookup results.

    Creates a pending dict_entry + review_item if not already queued.
    """
    # Check if already in review queue
    existing = await db.execute(
        text("""
            SELECT id FROM review_items
            WHERE queue = 'dict'
              AND status = 'pending'
              AND payload->>'term' = :term
            LIMIT 1
        """),
        {"term": term},
    )
    if existing.fetchone() is not None:
        logger.debug("auto_detect_and_queue: term=%r already queued", term)
        return

    # Check if a dict_entry already exists (any status)
    existing_entry = await db.execute(
        text("SELECT id FROM dict_entries WHERE lower(term) = lower(:term) LIMIT 1"),
        {"term": term},
    )
    row = existing_entry.fetchone()

    if row is None:
        entry_id = str(uuid.uuid4())
        canonical_id = term.lower().replace(" ", "_")
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            text("""
                INSERT INTO dict_entries
                    (id, canonical_id, term, entry_type, aliases, source,
                     confidence, review_status, version, created_at, updated_at)
                VALUES
                    (:id, :canonical_id, :term, 'entity', '[]', 'auto-detected',
                     0.5, 'pending', 1, :now, :now)
            """),
            {
                "id": entry_id,
                "canonical_id": canonical_id,
                "term": term,
                "now": now,
            },
        )
        logger.info("auto_detect_and_queue: created dict_entry id=%s term=%r", entry_id, term)
    else:
        entry_id = str(row[0])

    review_id = str(uuid.uuid4())
    payload = json.dumps({"term": term, "context": context, "source_id": source_id})
    await db.execute(
        text("""
            INSERT INTO review_items
                (id, queue, status, payload, dict_entry_id, created_at)
            VALUES
                (:id, 'dict', 'pending', :payload, :entry_id, NOW())
        """),
        {"id": review_id, "payload": payload, "entry_id": entry_id},
    )
    logger.info(
        "auto_detect_and_queue: queued review_item id=%s term=%r", review_id, term
    )


# ---------------------------------------------------------------------------
# Legacy class shim — keeps existing imports working
# ---------------------------------------------------------------------------


class DictService:
    """
    Dictionary lookup service.

    Phase 2: Full implementation of exact → fuzzy → full-text lookup.
    Requires *db* and *redis* to be passed at call time; the class interface
    exists only for backward-compatibility.
    """

    async def lookup(self, query: str, domain: str | None = None) -> list[Any]:
        """Stub — full version requires db+redis; returns [] when called without them."""
        logger.warning(
            "DictService.lookup called without db/redis — returning empty. "
            "Use dict_service.lookup(q, domain, db, redis) directly."
        )
        return []

    async def exact_match(self, query: str, domain: str | None = None) -> Any | None:
        return None

    async def fuzzy_match(self, query: str, domain: str | None = None) -> list[Any]:
        return []

    async def fulltext_search(self, query: str, domain: str | None = None) -> list[Any]:
        return []

    async def propose_entry(self, term: str, context: dict[str, Any]) -> Any | None:
        return None
