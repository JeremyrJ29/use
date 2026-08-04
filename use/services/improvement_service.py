"""
improvement_service.py — Continuous Improvement Loop

When a reviewer approves an item, this service re-processes affected documents
with updated Dict/Catalog/Graph knowledge, closing the feedback loop.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _write_improvement_log(
    log_id: str,
    trigger_type: str,
    trigger_id: str,
    affected_doc_ids: list[str],
    changes: dict,
    status: str,
    db: AsyncSession,
    error: str | None = None,
) -> None:
    await db.execute(
        text("""
            INSERT INTO improvement_log
                (id, trigger_type, trigger_id, affected_doc_ids, changes, status,
                 started_at, completed_at, created_at, error)
            VALUES
                (:id, :trigger_type, :trigger_id::uuid, :affected_doc_ids::jsonb,
                 :changes::jsonb, :status, NOW(), NOW(), NOW(), :error)
            ON CONFLICT (id) DO UPDATE
                SET affected_doc_ids = EXCLUDED.affected_doc_ids,
                    changes = EXCLUDED.changes,
                    status = EXCLUDED.status,
                    completed_at = NOW(),
                    error = EXCLUDED.error
        """),
        {
            "id": log_id,
            "trigger_type": trigger_type,
            "trigger_id": trigger_id,
            "affected_doc_ids": json.dumps(affected_doc_ids),
            "changes": json.dumps(changes),
            "status": status,
            "error": error,
        },
    )


async def _write_audit(action: str, entity_id: str, detail: dict, db: AsyncSession) -> None:
    await db.execute(
        text("""
            INSERT INTO audit_log (id, action, entity_type, entity_id, user_id, detail, created_at)
            VALUES (:id, :action, 'improvement', :entity_id, NULL, :detail, NOW())
        """),
        {
            "id": str(uuid.uuid4()),
            "action": action,
            "entity_id": entity_id,
            "detail": json.dumps(detail),
        },
    )


async def _get_lakehouse_docs_by_content(pattern: str, db: AsyncSession) -> list[dict]:
    """Find lakehouse_records whose md_content matches a LIKE pattern."""
    result = await db.execute(
        text("""
            SELECT id, ingestion_record_id, source_id, md_content, graph_node_ids, graph_edge_ids
            FROM lakehouse_records
            WHERE md_content LIKE :pattern
            LIMIT 200
        """),
        {"pattern": f"%{pattern}%"},
    )
    return [dict(r) for r in result.mappings().all()]


async def _get_lakehouse_docs_by_entity_tag(canonical_id: str, db: AsyncSession) -> list[dict]:
    """Find lakehouse_records tagged with entity:<canonical_id>."""
    result = await db.execute(
        text("""
            SELECT id, ingestion_record_id, source_id, md_content, graph_node_ids, graph_edge_ids
            FROM lakehouse_records
            WHERE md_tags::text LIKE :pattern
            LIMIT 200
        """),
        {"pattern": f"%entity:{canonical_id}%"},
    )
    return [dict(r) for r in result.mappings().all()]


async def _update_md_content(doc_id: str, new_md: str, db: AsyncSession) -> None:
    word_count = len(new_md.split())
    tags: list[str] = []
    flags: list[str] = []
    for line in new_md.splitlines()[:15]:
        if line.startswith("tags:"):
            raw = line.replace("tags:", "").strip().strip("[]")
            tags = [t.strip() for t in raw.split(",") if t.strip()]
        if line.startswith("flags:"):
            raw = line.replace("flags:", "").strip().strip("[]")
            flags = [f.strip() for f in raw.split(",") if f.strip()]
    await db.execute(
        text("""
            UPDATE lakehouse_records
            SET md_content = :md, md_word_count = :wc,
                md_tags = :tags::jsonb, md_flags = :flags::jsonb
            WHERE id = :id
        """),
        {
            "md": new_md,
            "wc": word_count,
            "tags": json.dumps(tags),
            "flags": json.dumps(flags),
            "id": doc_id,
        },
    )


def _substitute_entity_in_md(md: str, term: str, canonical_id: str) -> str:
    """Replace [UNKNOWN:term] and [AMBIGUOUS:term ...] tags in md_content."""
    # Replace exact UNKNOWN tag
    md = md.replace(f"[UNKNOWN: {term}]", "")
    md = re.sub(rf"\[AMBIGUOUS: {re.escape(term)}[^\]]*\]", "", md)
    # Update the entity line: replace 'UNKNOWN — term' with canonical — term
    md = re.sub(
        rf"(- \*\*\[[^\]]+\]:\*\* )UNKNOWN( — {re.escape(term)})",
        rf"\g<1>{canonical_id}\g<2>",
        md,
    )
    return md


# ---------------------------------------------------------------------------
# Reprocess helper (Task 7.5)
# ---------------------------------------------------------------------------


async def reprocess_document(doc_id: str, db: AsyncSession) -> dict:
    """
    Re-run Dict entity resolution on a lakehouse_record using updated knowledge,
    rebuild MD Layer, rebuild graph, and trigger pattern analysis.
    """
    result = await db.execute(
        text("""
            SELECT lr.id, lr.ingestion_record_id, lr.source_id, lr.md_content,
                   lr.graph_node_ids, lr.graph_edge_ids,
                   ir.source_type, ir.raw_payload, ir.metadata
            FROM lakehouse_records lr
            LEFT JOIN ingestion_records ir ON lr.ingestion_record_id = ir.id
            WHERE lr.id = :id
        """),
        {"id": doc_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        logger.warning("reprocess_document: doc %s not found", doc_id)
        return {"doc_id": doc_id, "error": "not_found"}

    row = dict(row)
    entities_updated = 0
    edges_updated = 0

    try:
        from use.services import structuring as _structuring
        from use.services.dict_service import lookup as _dict_lookup

        # Re-resolve entities mentioned in md_content
        # Find all UNKNOWN and AMBIGUOUS tags
        md = row["md_content"] or ""
        unknown_terms = re.findall(r"\[UNKNOWN: ([^\]]+)\]", md)
        ambiguous_terms = re.findall(r"\[AMBIGUOUS: ([^\| ]+)", md)
        terms_to_resolve = list(set(unknown_terms + ambiguous_terms))

        for term in terms_to_resolve:
            try:
                results = await _dict_lookup(term, domain=None, db=db)
                if results and results[0].confidence >= 0.7:
                    canonical_id = results[0].canonical_id
                    md = _substitute_entity_in_md(md, term, canonical_id)
                    entities_updated += 1
            except Exception as exc:
                logger.warning("reprocess_document: dict lookup failed for %s: %s", term, exc)

        if entities_updated > 0:
            await _update_md_content(doc_id, md, db)

        # Rebuild graph from document
        try:
            from use.services import graph_service as _graph
            from use.models.lakehouse import LakehouseRecord, MDLayerContent, GraphLayerRef

            lh = LakehouseRecord(
                use_doc_id=uuid.UUID(doc_id) if isinstance(doc_id, str) else doc_id,
                ingestion_record_id=row.get("ingestion_record_id"),
                source_id=row.get("source_id", ""),
                md_layer=MDLayerContent(content=md, word_count=len(md.split())),
                graph_layer=GraphLayerRef(
                    node_ids=row.get("graph_node_ids") or [],
                    edge_ids=row.get("graph_edge_ids") or [],
                ),
            )
            await _graph.build_from_document(lh, db)
            edges_updated = 1
        except Exception as exc:
            logger.warning("reprocess_document: graph rebuild failed for %s: %s", doc_id, exc)

        # Fire-and-forget pattern analysis via NATS
        try:
            from use.bus.nats_bus import NatsBus
            from use.config import get_settings
            bus = NatsBus(get_settings().nats_url)
            await bus.publish("use.pattern.analyze", {"doc_id": doc_id, "source": "improvement"})
        except Exception as exc:
            logger.debug("reprocess_document: pattern publish skipped: %s", exc)

    except Exception as exc:
        logger.error("reprocess_document: error for %s: %s", doc_id, exc)
        return {"doc_id": doc_id, "error": str(exc)}

    return {
        "doc_id": doc_id,
        "entities_updated": entities_updated,
        "edges_updated": edges_updated,
        "patterns_triggered": 1 if entities_updated or edges_updated else 0,
    }


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_dict_approval(review_item_id: str, db: AsyncSession) -> dict:
    """
    Handle approval of a dict review item.
    Find affected docs containing UNKNOWN/AMBIGUOUS tags for the term,
    re-run entity resolution, update MD content + graph nodes.
    """
    log_id = str(uuid.uuid4())
    result = await db.execute(
        text("SELECT id, queue, payload FROM review_items WHERE id = :id"),
        {"id": review_item_id},
    )
    item = result.mappings().one_or_none()
    if item is None:
        logger.warning("handle_dict_approval: review_item %s not found", review_item_id)
        return {"error": "review_item_not_found", "review_item_id": review_item_id}

    payload = dict(item["payload"] or {})
    term = payload.get("term", "")
    canonical_id = payload.get("canonical_id", "")

    affected_doc_ids: list[str] = []
    changes: dict[str, Any] = {"term": term, "canonical_id": canonical_id, "docs_updated": 0}

    if term:
        docs_unknown = await _get_lakehouse_docs_by_content(f"[UNKNOWN: {term}]", db)
        docs_ambiguous = await _get_lakehouse_docs_by_content(f"[AMBIGUOUS: {term}", db)
        docs = {str(d["id"]): d for d in docs_unknown + docs_ambiguous}

        for doc_id, doc in docs.items():
            try:
                md = doc["md_content"] or ""
                if canonical_id:
                    md = _substitute_entity_in_md(md, term, canonical_id)
                else:
                    # Dict has been updated — try fresh lookup
                    from use.services.dict_service import lookup as _dict_lookup
                    results = await _dict_lookup(term, domain=None, db=db)
                    if results and results[0].confidence >= 0.7:
                        canonical_id = results[0].canonical_id
                        md = _substitute_entity_in_md(md, term, canonical_id)

                await _update_md_content(doc_id, md, db)

                # Update graph nodes that referenced the UNKNOWN entity
                unknown_canon = f"unknown:{term.lower().replace(' ', '_')}"
                if canonical_id:
                    await db.execute(
                        text("""
                            UPDATE graph_nodes
                            SET canonical_id = :new_id, layer = 'human_confirmed'
                            WHERE canonical_id = :old_id
                        """),
                        {"new_id": canonical_id, "old_id": unknown_canon},
                    )

                affected_doc_ids.append(doc_id)
            except Exception as exc:
                logger.warning("handle_dict_approval: doc %s error: %s", doc_id, exc)

        changes["docs_updated"] = len(affected_doc_ids)

    await _write_improvement_log(log_id, "dict_approval", review_item_id, affected_doc_ids, changes, "complete", db)
    await _write_audit("dict_approval", review_item_id, changes, db)
    logger.info("handle_dict_approval: %s docs updated for term=%s", len(affected_doc_ids), term)
    return {"improvement_log_id": log_id, "affected_docs": len(affected_doc_ids), "changes": changes}


async def handle_catalog_confirm(canonical_id: str, db: AsyncSession) -> dict:
    """
    Handle catalog confirmation for an entity.
    Find all docs tagged with entity:<canonical_id>, rebuild graph with human_confirmed layer.
    """
    log_id = str(uuid.uuid4())
    docs = await _get_lakehouse_docs_by_entity_tag(canonical_id, db)
    affected_doc_ids = [str(d["id"]) for d in docs]
    edges_updated = 0

    for doc in docs:
        try:
            from use.services import graph_service as _graph
            from use.models.lakehouse import LakehouseRecord, MDLayerContent, GraphLayerRef

            doc_id = str(doc["id"])
            lh = LakehouseRecord(
                use_doc_id=uuid.UUID(doc_id),
                ingestion_record_id=doc.get("ingestion_record_id"),
                source_id=doc.get("source_id", ""),
                md_layer=MDLayerContent(
                    content=doc.get("md_content", ""),
                    word_count=len((doc.get("md_content") or "").split()),
                ),
                graph_layer=GraphLayerRef(
                    node_ids=doc.get("graph_node_ids") or [],
                    edge_ids=doc.get("graph_edge_ids") or [],
                ),
            )
            await _graph.build_from_document(lh, db)
            edges_updated += 1
        except Exception as exc:
            logger.warning("handle_catalog_confirm: graph rebuild error for %s: %s", doc.get("id"), exc)

    changes = {"canonical_id": canonical_id, "docs_reprocessed": len(affected_doc_ids), "edges_updated": edges_updated}
    await _write_improvement_log(log_id, "catalog_confirm", canonical_id, affected_doc_ids, changes, "complete", db)
    await _write_audit("catalog_confirm", canonical_id, changes, db)
    logger.info("handle_catalog_confirm: %s docs for entity=%s", len(affected_doc_ids), canonical_id)
    return {"improvement_log_id": log_id, "affected_docs": len(affected_doc_ids), "changes": changes}


async def handle_graph_confirm(edge_id: str, db: AsyncSession) -> dict:
    """
    Handle graph edge confirmation.
    Promote edge from inferred → human_confirmed and re-run pattern analysis.
    """
    log_id = str(uuid.uuid4())

    # Promote edge layer
    edge_result = await db.execute(
        text("""
            UPDATE graph_edges
            SET layer = 'human_confirmed'
            WHERE id = :id
            RETURNING id, source_node_id, target_node_id, source_doc_id
        """),
        {"id": edge_id},
    )
    edge_row = edge_result.mappings().one_or_none()

    if edge_row is None:
        logger.warning("handle_graph_confirm: edge %s not found", edge_id)
        await _write_improvement_log(log_id, "graph_confirm", edge_id, [], {"error": "edge_not_found"}, "failed", db)
        return {"error": "edge_not_found", "edge_id": edge_id}

    edge_row = dict(edge_row)
    source_doc_id = edge_row.get("source_doc_id")
    affected_doc_ids = [str(source_doc_id)] if source_doc_id else []

    # Re-run pattern analysis on affected entity pair
    try:
        from use.services.pattern_service import PatternService
        from use.models.lakehouse import LakehouseRecord, MDLayerContent, GraphLayerRef

        entity_ids = [str(edge_row.get("source_node_id", "")), str(edge_row.get("target_node_id", ""))]
        ps = PatternService()
        if source_doc_id:
            doc_result = await db.execute(
                text("SELECT id, source_id, md_content, graph_node_ids, graph_edge_ids FROM lakehouse_records WHERE id = :id"),
                {"id": str(source_doc_id)},
            )
            doc_row = doc_result.mappings().one_or_none()
            if doc_row:
                doc_row = dict(doc_row)
                lh = LakehouseRecord(
                    use_doc_id=uuid.UUID(str(doc_row["id"])),
                    source_id=doc_row.get("source_id", ""),
                    md_layer=MDLayerContent(content=doc_row.get("md_content", ""), word_count=0),
                    graph_layer=GraphLayerRef(
                        node_ids=doc_row.get("graph_node_ids") or [],
                        edge_ids=doc_row.get("graph_edge_ids") or [],
                    ),
                )
                await ps.analyze(lh, db)
    except Exception as exc:
        logger.warning("handle_graph_confirm: pattern analysis error: %s", exc)

    changes = {"edge_id": edge_id, "promoted_to": "human_confirmed", "entity_ids": entity_ids if source_doc_id else []}
    await _write_improvement_log(log_id, "graph_confirm", edge_id, affected_doc_ids, changes, "complete", db)
    await _write_audit("graph_confirm", edge_id, changes, db)
    logger.info("handle_graph_confirm: edge %s promoted to human_confirmed", edge_id)
    return {"improvement_log_id": log_id, "edge_id": edge_id, "changes": changes}


async def handle_anomaly_acknowledge(anomaly_flag_id: str, db: AsyncSession) -> dict:
    """
    Handle anomaly acknowledgement.
    Re-run structuring on source doc to see if anomaly is now resolved.
    """
    log_id = str(uuid.uuid4())

    # Ensure anomaly_flag is marked acknowledged
    await db.execute(
        text("UPDATE anomaly_flags SET acknowledged = TRUE WHERE id = :id"),
        {"id": anomaly_flag_id},
    )

    # Find source document
    flag_result = await db.execute(
        text("SELECT id, source_doc_id, detail FROM anomaly_flags WHERE id = :id"),
        {"id": anomaly_flag_id},
    )
    flag_row = flag_result.mappings().one_or_none()
    if flag_row is None:
        logger.warning("handle_anomaly_acknowledge: flag %s not found", anomaly_flag_id)
        await _write_improvement_log(log_id, "anomaly_acknowledge", anomaly_flag_id, [], {"error": "flag_not_found"}, "failed", db)
        return {"error": "flag_not_found", "anomaly_flag_id": anomaly_flag_id}

    flag_row = dict(flag_row)
    source_doc_id = flag_row.get("source_doc_id")
    affected_doc_ids = [str(source_doc_id)] if source_doc_id else []
    resolved = False

    if source_doc_id:
        try:
            reprocess_result = await reprocess_document(str(source_doc_id), db)
            resolved = reprocess_result.get("entities_updated", 0) > 0

            if resolved:
                # Mark anomaly as resolved in detail JSONB
                detail = dict(flag_row.get("detail") or {})
                detail["resolved"] = True
                await db.execute(
                    text("UPDATE anomaly_flags SET detail = :detail::jsonb WHERE id = :id"),
                    {"detail": json.dumps(detail), "id": anomaly_flag_id},
                )
        except Exception as exc:
            logger.warning("handle_anomaly_acknowledge: reprocess error for %s: %s", source_doc_id, exc)

    changes = {"anomaly_flag_id": anomaly_flag_id, "source_doc_id": str(source_doc_id) if source_doc_id else None, "resolved": resolved}
    await _write_improvement_log(log_id, "anomaly_acknowledge", anomaly_flag_id, affected_doc_ids, changes, "complete", db)
    await _write_audit("anomaly_acknowledge", anomaly_flag_id, changes, db)
    logger.info("handle_anomaly_acknowledge: flag %s acknowledged, resolved=%s", anomaly_flag_id, resolved)
    return {"improvement_log_id": log_id, "anomaly_flag_id": anomaly_flag_id, "resolved": resolved, "changes": changes}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


async def route_improvement(review_item: dict, db: AsyncSession) -> dict:
    """
    Inspect review_item and dispatch to the appropriate handler.
    """
    queue = review_item.get("queue", "")
    item_id = review_item.get("id", "")
    payload = review_item.get("payload") or {}

    logger.info("route_improvement: queue=%s item=%s", queue, item_id)

    try:
        if queue == "dict":
            return await handle_dict_approval(item_id, db)
        elif queue in ("ontology", "catalog"):
            canonical_id = payload.get("canonical_id", item_id)
            return await handle_catalog_confirm(canonical_id, db)
        elif queue == "graph":
            edge_id = payload.get("edge_id", item_id)
            return await handle_graph_confirm(edge_id, db)
        elif queue == "anomaly":
            anomaly_flag_id = payload.get("anomaly_flag_id", item_id)
            return await handle_anomaly_acknowledge(anomaly_flag_id, db)
        else:
            logger.warning("route_improvement: unknown queue=%s for item=%s", queue, item_id)
            return {"warning": f"no handler for queue={queue}", "item_id": item_id}
    except Exception as exc:
        logger.error("route_improvement: unhandled error for item=%s: %s", item_id, exc)
        return {"error": str(exc), "item_id": item_id}


# ---------------------------------------------------------------------------
# Log queries
# ---------------------------------------------------------------------------


async def get_improvement_log(limit: int, db: AsyncSession) -> list[dict]:
    """Return recent improvement_log records ordered by created_at DESC."""
    result = await db.execute(
        text("""
            SELECT id, trigger_type, trigger_id, affected_doc_ids, changes,
                   status, started_at, completed_at, created_at, error
            FROM improvement_log
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {"limit": limit},
    )
    rows = []
    for row in result.mappings().all():
        r = dict(row)
        r["id"] = str(r["id"])
        r["trigger_id"] = str(r["trigger_id"])
        r["created_at"] = r["created_at"].isoformat() if r.get("created_at") else None
        r["started_at"] = r["started_at"].isoformat() if r.get("started_at") else None
        r["completed_at"] = r["completed_at"].isoformat() if r.get("completed_at") else None
        rows.append(r)
    return rows


async def get_improvement_stats(db: AsyncSession) -> dict:
    """Return counts of improvement_log by trigger_type and status."""
    result = await db.execute(
        text("""
            SELECT trigger_type, status, COUNT(*) as count
            FROM improvement_log
            GROUP BY trigger_type, status
            ORDER BY trigger_type, status
        """)
    )
    rows = result.mappings().all()
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    total = 0
    for row in rows:
        tt = row["trigger_type"]
        st = row["status"]
        c = row["count"]
        by_type[tt] = by_type.get(tt, 0) + c
        by_status[st] = by_status.get(st, 0) + c
        total += c
    return {"total": total, "by_trigger_type": by_type, "by_status": by_status}
