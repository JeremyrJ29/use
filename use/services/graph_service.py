"""
graph_service.py — Core graph operations for the Semantic Graph Engine.

Postgres is the authoritative store. Neo4j is a sync target (failures are
logged but never propagated to callers).
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from use.models.graph import GraphEdge, GraphNode
from use.models.review import ReviewItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Predicate → edge_type mapping
# ---------------------------------------------------------------------------

PREDICATE_MAP: dict[str, str] = {
    "produces": "PRODUCES",
    "created": "PRODUCES",
    "generated": "PRODUCES",
    "caused": "CAUSED",
    "triggered": "CAUSED",
    "resulted in": "CAUSED",
    "follows": "FOLLOWS",
    "after": "FOLLOWS",
    "precedes": "FOLLOWS",
    "relates to": "RELATES_TO",
    "associated with": "RELATES_TO",
    "linked to": "RELATES_TO",
    "contradicts": "CONTRADICTS",
    "conflicts with": "CONTRADICTS",
}
_DEFAULT_EDGE_TYPE = "RELATES_TO"


def _map_predicate(predicate: str) -> str:
    lower = predicate.strip().lower()
    return PREDICATE_MAP.get(lower, _DEFAULT_EDGE_TYPE)


# ---------------------------------------------------------------------------
# Neo4j helpers (imported lazily to avoid hard dependency at module load)
# ---------------------------------------------------------------------------

def _get_driver():
    try:
        from use.db.neo4j import get_driver
        return get_driver()
    except Exception as exc:
        logger.warning("Neo4j driver unavailable: %s", exc)
        return None


async def _neo4j_upsert(node: GraphNode) -> None:
    driver = _get_driver()
    if driver is None:
        return
    try:
        from use.db.neo4j import neo4j_upsert_node
        await neo4j_upsert_node(driver, node)
    except Exception as exc:
        logger.warning("Neo4j upsert_node error: %s", exc)


async def _neo4j_edge(edge: GraphEdge) -> None:
    driver = _get_driver()
    if driver is None:
        return
    try:
        from use.db.neo4j import neo4j_create_edge
        await neo4j_create_edge(driver, edge)
    except Exception as exc:
        logger.warning("Neo4j create_edge error: %s", exc)


# ---------------------------------------------------------------------------
# Core DB operations
# ---------------------------------------------------------------------------

async def upsert_node(
    node_type: str,
    canonical_id: str | None,
    properties: dict,
    source_doc_id: str | None,
    db: AsyncSession,
) -> GraphNode:
    """
    Upsert a graph node. If a node with (node_type, canonical_id) exists,
    update its properties and return it. Otherwise INSERT a new one.
    """
    existing = None
    if canonical_id:
        row = await db.execute(
            text(
                "SELECT id, node_type, canonical_id, properties, source_doc_id, created_at "
                "FROM graph_nodes WHERE node_type = :nt AND canonical_id = :cid LIMIT 1"
            ),
            {"nt": node_type, "cid": canonical_id},
        )
        existing = row.mappings().first()

    if existing:
        # Merge properties
        merged: dict = dict(existing["properties"] or {})
        merged.update(properties)
        await db.execute(
            text("UPDATE graph_nodes SET properties = :props::jsonb WHERE id = :id"),
            {"props": _json_str(merged), "id": str(existing["id"])},
        )
        node = GraphNode(
            id=existing["id"],
            node_type=node_type,  # type: ignore[arg-type]
            canonical_id=canonical_id,
            properties=merged,
            source_doc_id=existing["source_doc_id"],
            created_at=existing["created_at"],
        )
    else:
        node_id = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO graph_nodes (id, node_type, canonical_id, properties, source_doc_id) "
                "VALUES (:id, :nt, :cid, :props::jsonb, :src)"
            ),
            {
                "id": str(node_id),
                "nt": node_type,
                "cid": canonical_id,
                "props": _json_str(properties),
                "src": source_doc_id,
            },
        )
        node = GraphNode(
            id=node_id,
            node_type=node_type,  # type: ignore[arg-type]
            canonical_id=canonical_id,
            properties=properties,
            source_doc_id=uuid.UUID(source_doc_id) if source_doc_id else None,
        )

    await _neo4j_upsert(node)
    return node


async def create_edge(
    from_node_id: str,
    to_node_id: str,
    edge_type: str,
    layer: str,
    confidence: float,
    properties: dict,
    source_doc_id: str | None,
    db: AsyncSession,
) -> GraphEdge:
    edge_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO graph_edges "
            "(id, from_node_id, to_node_id, edge_type, layer, confidence, properties, source_doc_id) "
            "VALUES (:id, :fn, :tn, :et, :layer, :conf, :props::jsonb, :src)"
        ),
        {
            "id": str(edge_id),
            "fn": from_node_id,
            "tn": to_node_id,
            "et": edge_type,
            "layer": layer,
            "conf": confidence,
            "props": _json_str(properties),
            "src": source_doc_id,
        },
    )
    edge = GraphEdge(
        id=edge_id,
        from_node_id=uuid.UUID(from_node_id),
        to_node_id=uuid.UUID(to_node_id),
        edge_type=edge_type,  # type: ignore[arg-type]
        layer=layer,  # type: ignore[arg-type]
        confidence=confidence,
        properties=properties,
        source_doc_id=uuid.UUID(source_doc_id) if source_doc_id else None,
    )
    await _neo4j_edge(edge)
    return edge


# ---------------------------------------------------------------------------
# Review item helper
# ---------------------------------------------------------------------------

async def _create_review_item(queue: str, payload: dict, db: AsyncSession) -> None:
    item_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO review_items (id, queue, status, payload) "
            "VALUES (:id, :queue, 'pending', :payload::jsonb)"
        ),
        {"id": str(item_id), "queue": queue, "payload": _json_str(payload)},
    )


# ---------------------------------------------------------------------------
# build_from_document
# ---------------------------------------------------------------------------

async def build_from_document(lakehouse_record: Any, db: AsyncSession) -> None:
    """
    Parse the MD Layer document and build graph nodes + edges.

    Handles malformed/empty sections gracefully — never raises.
    """
    doc_id = str(lakehouse_record.use_doc_id)

    try:
        # 1. Create Document node
        doc_node = await upsert_node(
            node_type="Document",
            canonical_id=f"doc:{doc_id}",
            properties={"source_id": lakehouse_record.source_id},
            source_doc_id=doc_id,
            db=db,
        )

        md_content: str = ""
        try:
            md_content = lakehouse_record.md_layer.content or ""
        except AttributeError:
            try:
                md_content = lakehouse_record.md_content or ""
            except AttributeError:
                logger.warning("graph_service: could not read md_content for %s", doc_id)

        entity_nodes: dict[str, GraphNode] = {}  # name -> node

        # 2. Parse ## Entities section
        entity_section = _extract_section(md_content, "Entities")
        for line in entity_section.splitlines():
            line = line.strip().lstrip("-").lstrip("*").strip()
            if not line:
                continue
            # Format: "Name (type)" or just "Name"
            name, etype = _parse_entity_line(line)
            try:
                node = await upsert_node(
                    node_type="Entity",
                    canonical_id=_canonicalize(name),
                    properties={"name": name, "entity_type": etype},
                    source_doc_id=doc_id,
                    db=db,
                )
                entity_nodes[name.lower()] = node
                # DOCUMENTED_IN edge
                await create_edge(
                    from_node_id=str(node.id),
                    to_node_id=str(doc_node.id),
                    edge_type="DOCUMENTED_IN",
                    layer="factual",
                    confidence=1.0,
                    properties={},
                    source_doc_id=doc_id,
                    db=db,
                )
            except Exception as exc:
                logger.warning("graph_service: error upserting entity '%s': %s", name, exc)

        # 3. Parse ## Relationships section
        # Format: [SUBJECT] → [PREDICATE] → [OBJECT]
        rel_section = _extract_section(md_content, "Relationships")
        for line in rel_section.splitlines():
            line = line.strip().lstrip("-").lstrip("*").strip()
            if not line:
                continue
            parts = [p.strip().strip("[]") for p in re.split(r"→|->", line)]
            if len(parts) != 3:
                continue
            subj, pred, obj = parts
            edge_type = _map_predicate(pred)
            from_node = entity_nodes.get(subj.lower())
            to_node = entity_nodes.get(obj.lower())
            if from_node is None:
                try:
                    from_node = await upsert_node("Entity", _canonicalize(subj), {"name": subj}, doc_id, db)
                    entity_nodes[subj.lower()] = from_node
                except Exception as exc:
                    logger.warning("graph_service: error upserting subject '%s': %s", subj, exc)
                    continue
            if to_node is None:
                try:
                    to_node = await upsert_node("Entity", _canonicalize(obj), {"name": obj}, doc_id, db)
                    entity_nodes[obj.lower()] = to_node
                except Exception as exc:
                    logger.warning("graph_service: error upserting object '%s': %s", obj, exc)
                    continue

            # Check for contradiction: same (from, to, edge_type) with conflicting props
            try:
                existing_edge = await _find_existing_edge(
                    str(from_node.id), str(to_node.id), edge_type, db
                )
                if existing_edge:
                    # Contradiction detected
                    contra = await create_edge(
                        from_node_id=str(from_node.id),
                        to_node_id=str(to_node.id),
                        edge_type="CONTRADICTS",
                        layer="factual",
                        confidence=1.0,
                        properties={"original_edge_id": existing_edge, "predicate": pred},
                        source_doc_id=doc_id,
                        db=db,
                    )
                    await _create_review_item(
                        queue="anomaly",
                        payload={
                            "from_canonical_id": from_node.canonical_id,
                            "to_canonical_id": to_node.canonical_id,
                            "edge_type": edge_type,
                            "conflicting_values": {"predicate": pred},
                            "source_doc_id": doc_id,
                            "contradicts_edge_id": str(contra.id),
                        },
                        db=db,
                    )
                else:
                    await create_edge(
                        from_node_id=str(from_node.id),
                        to_node_id=str(to_node.id),
                        edge_type=edge_type,
                        layer="factual",
                        confidence=1.0,
                        properties={"predicate": pred},
                        source_doc_id=doc_id,
                        db=db,
                    )
            except Exception as exc:
                logger.warning("graph_service: error creating relationship edge: %s", exc)

        # 4. Parse ## Values section → Fact nodes
        values_section = _extract_section(md_content, "Values")
        for line in values_section.splitlines():
            line = line.strip().lstrip("-").lstrip("*").strip()
            if not line:
                continue
            try:
                fact_node = await upsert_node(
                    node_type="Fact",
                    canonical_id=None,
                    properties={"raw": line, "source_doc_id": doc_id},
                    source_doc_id=doc_id,
                    db=db,
                )
                await create_edge(
                    from_node_id=str(fact_node.id),
                    to_node_id=str(doc_node.id),
                    edge_type="DOCUMENTED_IN",
                    layer="factual",
                    confidence=1.0,
                    properties={},
                    source_doc_id=doc_id,
                    db=db,
                )
            except Exception as exc:
                logger.warning("graph_service: error creating Fact node: %s", exc)

        # 5. Check for missing links via ontology rules
        for name, node in entity_nodes.items():
            entity_type = (node.properties or {}).get("entity_type", "")
            if not entity_type:
                continue
            try:
                expected = await _get_ontology_expected_edges(entity_type, db)
                for expected_edge_type in expected:
                    has_edge = await _node_has_edge_type(str(node.id), expected_edge_type, db)
                    if not has_edge:
                        missing = await create_edge(
                            from_node_id=str(node.id),
                            to_node_id=str(doc_node.id),
                            edge_type="MISSING_LINK",
                            layer="inferred",
                            confidence=0.5,
                            properties={
                                "expected_edge_type": expected_edge_type,
                                "entity_type": entity_type,
                            },
                            source_doc_id=doc_id,
                            db=db,
                        )
                        await _create_review_item(
                            queue="gap",
                            payload={
                                "entity_canonical_id": node.canonical_id,
                                "expected_edge_type": expected_edge_type,
                                "reason": f"Ontology rule: {entity_type} should have {expected_edge_type}",
                                "missing_link_edge_id": str(missing.id),
                            },
                            db=db,
                        )
            except Exception as exc:
                logger.warning("graph_service: error checking ontology gaps for %s: %s", name, exc)

        logger.info("graph_service: built graph for doc=%s (%d entities)", doc_id, len(entity_nodes))

    except Exception as exc:
        logger.warning("graph_service: build_from_document failed for %s: %s", doc_id, exc)


# ---------------------------------------------------------------------------
# confirm_edge
# ---------------------------------------------------------------------------

async def confirm_edge(edge_id: str, reviewer_id: str, db: AsyncSession) -> GraphEdge:
    await db.execute(
        text(
            "UPDATE graph_edges SET layer = 'human_confirmed', confidence = 1.0 WHERE id = :id"
        ),
        {"id": edge_id},
    )
    # Write audit log
    await db.execute(
        text(
            "INSERT INTO audit_log (action, entity_type, entity_id, user_id, detail) "
            "VALUES ('confirm_edge', 'graph_edge', :eid, :uid, :detail::jsonb)"
        ),
        {
            "eid": edge_id,
            "uid": reviewer_id,
            "detail": _json_str({"edge_id": edge_id, "reviewer_id": reviewer_id}),
        },
    )
    edge = await _get_edge_by_id(edge_id, db)
    if edge is None:
        raise ValueError(f"Edge {edge_id} not found after confirm")
    # Sync to Neo4j
    await _neo4j_edge(edge)
    return edge


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

async def get_entity_node(canonical_id: str, db: AsyncSession) -> GraphNode | None:
    row = await db.execute(
        text(
            "SELECT id, node_type, canonical_id, properties, source_doc_id, created_at "
            "FROM graph_nodes WHERE canonical_id = :cid LIMIT 1"
        ),
        {"cid": canonical_id},
    )
    r = row.mappings().first()
    if r is None:
        return None
    return _row_to_node(r)


async def get_node_relationships(
    node_id: str,
    layer: str | None,
    db: AsyncSession,
) -> list[GraphEdge]:
    if layer:
        rows = await db.execute(
            text(
                "SELECT id, from_node_id, to_node_id, edge_type, layer, confidence, "
                "properties, source_doc_id, acknowledged, created_at "
                "FROM graph_edges WHERE (from_node_id = :nid OR to_node_id = :nid) "
                "AND layer = :layer ORDER BY created_at DESC"
            ),
            {"nid": node_id, "layer": layer},
        )
    else:
        rows = await db.execute(
            text(
                "SELECT id, from_node_id, to_node_id, edge_type, layer, confidence, "
                "properties, source_doc_id, acknowledged, created_at "
                "FROM graph_edges WHERE from_node_id = :nid OR to_node_id = :nid "
                "ORDER BY created_at DESC"
            ),
            {"nid": node_id},
        )
    return [_row_to_edge(r) for r in rows.mappings().all()]


async def traverse(from_node_id: str, depth: int, db: AsyncSession) -> dict:
    """
    Recursive Postgres traversal up to depth (max 4).
    Returns adjacency dict: {node_id: {canonical_id, edges: [{to_id, edge_type, layer}]}}
    """
    depth = min(depth, 4)

    # Use recursive CTE for breadth-first traversal
    result = await db.execute(
        text(
            """
            WITH RECURSIVE traverse AS (
                SELECT
                    e.id AS edge_id,
                    e.from_node_id,
                    e.to_node_id,
                    e.edge_type,
                    e.layer,
                    e.confidence,
                    1 AS depth
                FROM graph_edges e
                WHERE e.from_node_id = :start_id

                UNION ALL

                SELECT
                    e.id,
                    e.from_node_id,
                    e.to_node_id,
                    e.edge_type,
                    e.layer,
                    e.confidence,
                    t.depth + 1
                FROM graph_edges e
                INNER JOIN traverse t ON e.from_node_id = t.to_node_id
                WHERE t.depth < :max_depth
            )
            SELECT DISTINCT
                t.from_node_id,
                t.to_node_id,
                t.edge_type,
                t.layer,
                n1.canonical_id AS from_canonical,
                n2.canonical_id AS to_canonical
            FROM traverse t
            LEFT JOIN graph_nodes n1 ON n1.id = t.from_node_id
            LEFT JOIN graph_nodes n2 ON n2.id = t.to_node_id
            """
        ),
        {"start_id": from_node_id, "max_depth": depth},
    )

    adjacency: dict[str, Any] = {}
    for row in result.mappings().all():
        fn = str(row["from_node_id"])
        tn = str(row["to_node_id"])
        if fn not in adjacency:
            adjacency[fn] = {"canonical_id": row["from_canonical"], "edges": []}
        adjacency[fn]["edges"].append({
            "to_id": tn,
            "edge_type": row["edge_type"],
            "layer": row["layer"],
        })
    return adjacency


async def get_gaps(db: AsyncSession) -> list[GraphEdge]:
    rows = await db.execute(
        text(
            "SELECT id, from_node_id, to_node_id, edge_type, layer, confidence, "
            "properties, source_doc_id, acknowledged, created_at "
            "FROM graph_edges WHERE edge_type = 'MISSING_LINK' AND acknowledged = FALSE "
            "ORDER BY created_at DESC"
        )
    )
    return [_row_to_edge(r) for r in rows.mappings().all()]


async def get_contradictions(db: AsyncSession) -> list[GraphEdge]:
    rows = await db.execute(
        text(
            "SELECT id, from_node_id, to_node_id, edge_type, layer, confidence, "
            "properties, source_doc_id, acknowledged, created_at "
            "FROM graph_edges WHERE edge_type = 'CONTRADICTS' AND acknowledged = FALSE "
            "ORDER BY created_at DESC"
        )
    )
    return [_row_to_edge(r) for r in rows.mappings().all()]


async def get_graph_summary(db: AsyncSession) -> dict:
    node_row = await db.execute(text("SELECT COUNT(*) AS cnt FROM graph_nodes"))
    node_count = node_row.scalar() or 0

    edge_row = await db.execute(text("SELECT COUNT(*) AS cnt FROM graph_edges"))
    edge_count = edge_row.scalar() or 0

    layer_rows = await db.execute(
        text("SELECT layer, COUNT(*) AS cnt FROM graph_edges GROUP BY layer")
    )
    layer_breakdown: dict[str, int] = {}
    for r in layer_rows.mappings().all():
        layer_breakdown[r["layer"]] = r["cnt"]

    gap_row = await db.execute(
        text("SELECT COUNT(*) AS cnt FROM graph_edges WHERE edge_type='MISSING_LINK' AND acknowledged=FALSE")
    )
    open_gaps = gap_row.scalar() or 0

    contra_row = await db.execute(
        text("SELECT COUNT(*) AS cnt FROM graph_edges WHERE edge_type='CONTRADICTS' AND acknowledged=FALSE")
    )
    open_contradictions = contra_row.scalar() or 0

    most_connected_rows = await db.execute(
        text(
            """
            SELECT n.canonical_id, COUNT(e.id) AS edge_count
            FROM graph_nodes n
            LEFT JOIN graph_edges e ON e.from_node_id = n.id OR e.to_node_id = n.id
            WHERE n.canonical_id IS NOT NULL
            GROUP BY n.canonical_id
            ORDER BY edge_count DESC
            LIMIT 5
            """
        )
    )
    most_connected = [
        {"canonical_id": r["canonical_id"], "edge_count": r["edge_count"]}
        for r in most_connected_rows.mappings().all()
    ]

    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "layer_breakdown": layer_breakdown,
        "open_gaps": open_gaps,
        "open_contradictions": open_contradictions,
        "most_connected": most_connected,
    }


# ---------------------------------------------------------------------------
# acknowledge_edge (for review API)
# ---------------------------------------------------------------------------

async def acknowledge_edge(edge_id: str, db: AsyncSession) -> GraphEdge:
    await db.execute(
        text("UPDATE graph_edges SET acknowledged = TRUE WHERE id = :id"),
        {"id": edge_id},
    )
    edge = await _get_edge_by_id(edge_id, db)
    if edge is None:
        raise ValueError(f"Edge {edge_id} not found")
    return edge


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _get_edge_by_id(edge_id: str, db: AsyncSession) -> GraphEdge | None:
    row = await db.execute(
        text(
            "SELECT id, from_node_id, to_node_id, edge_type, layer, confidence, "
            "properties, source_doc_id, acknowledged, created_at "
            "FROM graph_edges WHERE id = :id"
        ),
        {"id": edge_id},
    )
    r = row.mappings().first()
    if r is None:
        return None
    return _row_to_edge(r)


async def _find_existing_edge(
    from_id: str, to_id: str, edge_type: str, db: AsyncSession
) -> str | None:
    """Return the id of an existing edge with same (from, to, edge_type), or None."""
    row = await db.execute(
        text(
            "SELECT id FROM graph_edges "
            "WHERE from_node_id = :fn AND to_node_id = :tn AND edge_type = :et LIMIT 1"
        ),
        {"fn": from_id, "tn": to_id, "et": edge_type},
    )
    r = row.mappings().first()
    return str(r["id"]) if r else None


async def _node_has_edge_type(node_id: str, edge_type: str, db: AsyncSession) -> bool:
    row = await db.execute(
        text(
            "SELECT 1 FROM graph_edges "
            "WHERE from_node_id = :nid AND edge_type = :et LIMIT 1"
        ),
        {"nid": node_id, "et": edge_type},
    )
    return row.first() is not None


async def _get_ontology_expected_edges(entity_type: str, db: AsyncSession) -> list[str]:
    """Query ontology_entries for expected edge types for a given entity type."""
    try:
        rows = await db.execute(
            text(
                "SELECT name FROM ontology_entries "
                "WHERE ontology_type = 'edge_rule' AND domain = :et"
            ),
            {"et": entity_type},
        )
        return [r[0] for r in rows.all()]
    except Exception:
        return []


def _row_to_node(r: Any) -> GraphNode:
    return GraphNode(
        id=r["id"],
        node_type=r["node_type"],
        canonical_id=r["canonical_id"],
        properties=dict(r["properties"] or {}),
        source_doc_id=r["source_doc_id"],
        created_at=r["created_at"],
    )


def _row_to_edge(r: Any) -> GraphEdge:
    return GraphEdge(
        id=r["id"],
        from_node_id=r["from_node_id"],
        to_node_id=r["to_node_id"],
        edge_type=r["edge_type"],
        layer=r["layer"],
        confidence=float(r["confidence"]),
        properties=dict(r["properties"] or {}),
        source_doc_id=r.get("source_doc_id"),
        acknowledged=bool(r["acknowledged"]),
        created_at=r["created_at"],
    )


def _extract_section(md: str, section_name: str) -> str:
    """Extract content under a ## SectionName heading."""
    pattern = re.compile(
        rf"##\s+{re.escape(section_name)}\s*\n(.*?)(?=\n##|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(md)
    return m.group(1).strip() if m else ""


def _parse_entity_line(line: str) -> tuple[str, str]:
    """Parse 'Name (type)' or just 'Name'. Returns (name, entity_type)."""
    m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", line)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return line.strip(), "Entity"


def _canonicalize(name: str) -> str:
    """Simple canonical ID: lowercase, spaces → underscores."""
    return re.sub(r"\s+", "_", name.strip().lower())


def _json_str(obj: Any) -> str:
    import json
    return json.dumps(obj, default=str)
