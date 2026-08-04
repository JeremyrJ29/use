"""
pattern_service.py — Pattern Detection & Anomaly Engine.

Continuously analyses the Semantic Lakehouse to find recurring patterns and
flag anomalies.  Results are persisted to `pattern_records` and
`anomaly_flags`, and anomalies auto-create `review_items`.
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from collections import defaultdict
from itertools import combinations
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _write_audit(
    action: str,
    entity_id: str,
    detail: dict,
    db: AsyncSession,
) -> None:
    await db.execute(
        text("""
            INSERT INTO audit_log (id, action, entity_type, entity_id, user_id, detail, created_at)
            VALUES (:id, :action, 'anomaly_flag', :entity_id, NULL, :detail, NOW())
        """),
        {
            "id": str(uuid.uuid4()),
            "action": action,
            "entity_id": entity_id,
            "detail": json.dumps(detail),
        },
    )


async def _create_anomaly_review_item(
    anomaly_flag_id: str,
    anomaly_type: str,
    entity_ids: list[str],
    severity: float,
    detail: dict,
    db: AsyncSession,
) -> str:
    """
    Insert a review_item for the given anomaly flag, update the flag's
    review_item_id, write an audit entry, and return the new review_item id.
    """
    review_id = str(uuid.uuid4())
    payload = json.dumps(
        {
            "anomaly_flag_id": anomaly_flag_id,
            "anomaly_type": anomaly_type,
            "entity_ids": entity_ids,
            "severity": severity,
            **detail,
        }
    )
    await db.execute(
        text("""
            INSERT INTO review_items (id, queue, status, payload, created_at)
            VALUES (:id, 'anomaly', 'pending', :payload::jsonb, NOW())
        """),
        {"id": review_id, "payload": payload},
    )
    await db.execute(
        text("UPDATE anomaly_flags SET review_item_id = :rid WHERE id = :id"),
        {"rid": review_id, "id": anomaly_flag_id},
    )
    return review_id


async def _upsert_anomaly_flag(
    anomaly_type: str,
    source_doc_id: str | None,
    entity_ids: list[str],
    severity: float,
    detail: dict,
    db: AsyncSession,
) -> dict | None:
    """
    Insert an anomaly_flag only when no identical (anomaly_type, entity_ids)
    flag already exists.  Returns the flag dict or None if it was a duplicate.
    """
    existing = await db.execute(
        text("""
            SELECT id FROM anomaly_flags
            WHERE anomaly_type = :atype
              AND entity_ids::text = :eids_text
              AND acknowledged = FALSE
            LIMIT 1
        """),
        {
            "atype": anomaly_type,
            "eids_text": json.dumps(sorted(entity_ids)),
        },
    )
    if existing.fetchone():
        return None

    flag_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO anomaly_flags
                (id, anomaly_type, source_doc_id, entity_ids, severity, detail, created_at)
            VALUES (:id, :atype, :src, :eids::jsonb, :sev, :detail::jsonb, NOW())
        """),
        {
            "id": flag_id,
            "atype": anomaly_type,
            "src": source_doc_id,
            "eids": json.dumps(sorted(entity_ids)),
            "sev": severity,
            "detail": json.dumps(detail),
        },
    )
    review_id = await _create_anomaly_review_item(
        flag_id, anomaly_type, entity_ids, severity, detail, db
    )
    await _write_audit(
        "anomaly_flag_created",
        flag_id,
        {"anomaly_type": anomaly_type, "severity": severity, "review_item_id": review_id},
        db,
    )
    return {
        "id": flag_id,
        "anomaly_type": anomaly_type,
        "entity_ids": entity_ids,
        "severity": severity,
        "review_item_id": review_id,
    }


# ---------------------------------------------------------------------------
# 1. Co-occurrence / PMI
# ---------------------------------------------------------------------------


async def compute_co_occurrence(db: AsyncSession) -> list[dict]:
    """
    Compute pairwise PMI scores across all lakehouse_records and upsert
    results into `pattern_records`.
    """
    result = await db.execute(
        text("SELECT use_doc_id, md_tags FROM lakehouse_records WHERE md_tags IS NOT NULL")
    )
    rows = result.mappings().all()

    total_docs = len(rows)
    if total_docs < 2:
        return []

    # Parse entity tags: entries like "entity:<canonical_id>"
    doc_entities: list[set[str]] = []
    for row in rows:
        tags: list[str] = row["md_tags"] or []
        entities = {t[len("entity:"):] for t in tags if t.startswith("entity:")}
        doc_entities.append(entities)

    # Marginal counts
    entity_count: dict[str, int] = defaultdict(int)
    pair_count: dict[tuple[str, str], int] = defaultdict(int)

    for entities in doc_entities:
        for e in entities:
            entity_count[e] += 1
        for a, b in combinations(sorted(entities), 2):
            pair_count[(a, b)] += 1

    upserted: list[dict] = []
    for (a, b), co_count in pair_count.items():
        if co_count < 1:
            continue
        pa = entity_count[a] / total_docs
        pb = entity_count[b] / total_docs
        pab = co_count / total_docs
        if pa == 0 or pb == 0 or pab == 0:
            continue
        try:
            pmi = math.log2(pab / (pa * pb))
        except (ValueError, ZeroDivisionError):
            continue

        entity_ids_sorted = json.dumps([a, b])
        await db.execute(
            text("""
                INSERT INTO pattern_records
                    (id, pattern_type, entity_ids, score, support, first_seen, last_seen)
                VALUES
                    (gen_random_uuid(), 'co_occurrence', :eids::jsonb, :score, :support, NOW(), NOW())
                ON CONFLICT (pattern_type, (entity_ids::text))
                DO UPDATE SET
                    score    = EXCLUDED.score,
                    support  = EXCLUDED.support,
                    last_seen = NOW()
            """),
            {"eids": entity_ids_sorted, "score": pmi, "support": co_count},
        )
        upserted.append({"entity_ids": [a, b], "pmi": pmi, "support": co_count})

    logger.info("pattern_service: co_occurrence upserted %d pairs", len(upserted))
    return upserted


# ---------------------------------------------------------------------------
# 2. Sequence detection
# ---------------------------------------------------------------------------


async def detect_sequences(db: AsyncSession) -> list[dict]:
    """
    Build N-gram (n=2,3) sequences of edge predicates per entity chain and
    persist frequent ones.
    """
    result = await db.execute(
        text("""
            SELECT from_node_id, edge_type, created_at
            FROM graph_edges
            ORDER BY from_node_id, created_at
        """)
    )
    rows = result.mappings().all()

    # Group predicates by from_node
    node_preds: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        node_preds[str(row["from_node_id"])].append(row["edge_type"])

    seq_count: dict[tuple[str, ...], int] = defaultdict(int)
    seq_nodes: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for node_id, preds in node_preds.items():
        for n in (2, 3):
            for i in range(len(preds) - n + 1):
                ngram = tuple(preds[i : i + n])
                seq_count[ngram] += 1
                if node_id not in seq_nodes[ngram]:
                    seq_nodes[ngram].append(node_id)

    upserted: list[dict] = []
    for ngram, count in seq_count.items():
        if count < 2:
            continue
        seq_key = json.dumps(list(ngram))
        nodes = seq_nodes[ngram][:10]  # cap metadata size
        await db.execute(
            text("""
                INSERT INTO pattern_records
                    (id, pattern_type, entity_ids, score, support, first_seen, last_seen, metadata)
                VALUES
                    (gen_random_uuid(), 'sequence', :eids::jsonb, :score, :support,
                     NOW(), NOW(), :meta::jsonb)
                ON CONFLICT (pattern_type, (entity_ids::text))
                DO UPDATE SET
                    score    = EXCLUDED.score,
                    support  = EXCLUDED.support,
                    last_seen = NOW()
            """),
            {
                "eids": seq_key,
                "score": float(count),
                "support": count,
                "meta": json.dumps({"node_ids": nodes}),
            },
        )
        upserted.append({"sequence": list(ngram), "support": count})

    logger.info("pattern_service: sequence upserted %d patterns", len(upserted))
    return upserted


# ---------------------------------------------------------------------------
# 3. Drift detection (CUSUM)
# ---------------------------------------------------------------------------

_CUSUM_K = 0.5   # allowance / reference value
_CUSUM_H = 5.0   # decision threshold


def _cusum(values: list[float], k: float = _CUSUM_K, h: float = _CUSUM_H) -> bool:
    """Return True if CUSUM statistic exceeds threshold h."""
    if len(values) < 2:
        return False
    mean = sum(values) / len(values)
    s_pos = s_neg = 0.0
    for v in values:
        s_pos = max(0.0, s_pos + (v - mean) - k)
        s_neg = max(0.0, s_neg + (mean - v) - k)
        if s_pos > h or s_neg > h:
            return True
    return False


async def detect_drift(db: AsyncSession) -> list[dict]:
    """
    Query ingestion_records for any numeric values stored in structured zone
    and flag streams that exceed the CUSUM threshold.
    """
    result = await db.execute(
        text("""
            SELECT source_id, structured_payload
            FROM lakehouse_records
            WHERE structured_payload IS NOT NULL
            ORDER BY source_id, created_at
        """)
    )
    rows = result.mappings().all()

    # Collect numeric streams keyed by (source_id, field_name)
    streams: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        payload: dict[str, Any] = row["structured_payload"] or {}
        sid = str(row["source_id"])
        for k, v in payload.items():
            if isinstance(v, (int, float)):
                streams[(sid, k)].append(float(v))

    flagged: list[dict] = []
    for (source_id, field), values in streams.items():
        if not _cusum(values):
            continue
        detail = {
            "source_id": source_id,
            "field": field,
            "n_points": len(values),
            "mean": sum(values) / len(values),
        }
        flag = await _upsert_anomaly_flag(
            anomaly_type="drift",
            source_doc_id=None,
            entity_ids=[f"{source_id}:{field}"],
            severity=min(1.0, 0.5 + 0.1 * len(values) / 10),
            detail=detail,
            db=db,
        )
        if flag:
            flagged.append(flag)

    logger.info("pattern_service: drift detected %d anomalies", len(flagged))
    return flagged


# ---------------------------------------------------------------------------
# 4. Missing-pattern anomalies
# ---------------------------------------------------------------------------


async def detect_missing_patterns(db: AsyncSession) -> list[dict]:
    """
    For recently ingested documents, check if highly-scored co-occurrence pairs
    (PMI > 1.0) are absent when one of the entities is present.
    """
    # Load high-PMI pairs
    pairs_result = await db.execute(
        text("""
            SELECT entity_ids, score
            FROM pattern_records
            WHERE pattern_type = 'co_occurrence' AND score > 1.0
        """)
    )
    pairs = pairs_result.mappings().all()
    if not pairs:
        return []

    # Most recent 100 documents
    docs_result = await db.execute(
        text("""
            SELECT use_doc_id, md_tags
            FROM lakehouse_records
            WHERE md_tags IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 100
        """)
    )
    docs = docs_result.mappings().all()

    flagged: list[dict] = []
    for doc in docs:
        tags: list[str] = doc["md_tags"] or []
        doc_entities = {t[len("entity:"):] for t in tags if t.startswith("entity:")}
        doc_id = str(doc["use_doc_id"])

        for pair_row in pairs:
            pair: list[str] = pair_row["entity_ids"]
            pmi: float = pair_row["score"]
            if len(pair) < 2:
                continue
            a, b = pair[0], pair[1]
            # Only flag if one entity is present but the other is absent
            if (a in doc_entities) != (b in doc_entities):
                missing = b if a in doc_entities else a
                detail = {
                    "present_entity": a if a in doc_entities else b,
                    "missing_entity": missing,
                    "pmi_score": pmi,
                }
                flag = await _upsert_anomaly_flag(
                    anomaly_type="missing_pattern",
                    source_doc_id=doc_id,
                    entity_ids=[a, b],
                    severity=min(1.0, pmi / 5.0),
                    detail=detail,
                    db=db,
                )
                if flag:
                    flagged.append(flag)

    logger.info("pattern_service: missing_pattern flagged %d anomalies", len(flagged))
    return flagged


# ---------------------------------------------------------------------------
# 5. Structural anomalies (graph CONTRADICTS / MISSING_LINK)
# ---------------------------------------------------------------------------


async def detect_structural_anomalies(db: AsyncSession) -> list[dict]:
    """
    Query graph_edges for CONTRADICTS / MISSING_LINK edges not yet
    acknowledged and create anomaly_flags where none exist.
    """
    result = await db.execute(
        text("""
            SELECT e.id AS edge_id, e.edge_type, e.from_node_id, e.to_node_id,
                   e.source_doc_id, e.confidence
            FROM graph_edges e
            WHERE e.edge_type IN ('CONTRADICTS', 'MISSING_LINK')
              AND e.acknowledged = FALSE
        """)
    )
    edges = result.mappings().all()

    flagged: list[dict] = []
    for edge in edges:
        anomaly_type = (
            "contradiction" if edge["edge_type"] == "CONTRADICTS" else "missing_pattern"
        )
        entity_ids = [str(edge["from_node_id"]), str(edge["to_node_id"])]
        detail = {
            "edge_id": str(edge["edge_id"]),
            "edge_type": edge["edge_type"],
            "confidence": edge["confidence"],
        }
        flag = await _upsert_anomaly_flag(
            anomaly_type=anomaly_type,
            source_doc_id=str(edge["source_doc_id"]) if edge["source_doc_id"] else None,
            entity_ids=entity_ids,
            severity=float(edge["confidence"]),
            detail=detail,
            db=db,
        )
        if flag:
            flagged.append(flag)

    logger.info("pattern_service: structural anomalies flagged %d", len(flagged))
    return flagged


# ---------------------------------------------------------------------------
# 6. Run all detectors
# ---------------------------------------------------------------------------


async def run_pattern_analysis(db: AsyncSession) -> dict:
    """
    Execute all five detectors in sequence and return a summary.
    Individual detector failures are logged but never propagate.
    """
    summary: dict[str, int] = {
        "co_occurrence": 0,
        "sequences": 0,
        "drift": 0,
        "missing_patterns": 0,
        "structural": 0,
    }

    for key, coro in [
        ("co_occurrence", compute_co_occurrence(db)),
        ("sequences", detect_sequences(db)),
        ("drift", detect_drift(db)),
        ("missing_patterns", detect_missing_patterns(db)),
        ("structural", detect_structural_anomalies(db)),
    ]:
        try:
            result = await coro
            summary[key] = len(result)
        except Exception as exc:
            logger.error("pattern_service: %s detector failed: %s", key, exc)

    logger.info("pattern_service: analysis complete — %s", summary)
    return summary
