from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from use.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def get_neo4j_session() -> AsyncGenerator[AsyncSession, None]:
    driver = get_driver()
    async with driver.session() as session:
        yield session


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


# ---------------------------------------------------------------------------
# Sync helpers — all fail-safe (Neo4j unavailability must never crash callers)
# ---------------------------------------------------------------------------

async def neo4j_health_check(driver: AsyncDriver) -> bool:
    """Return True if Neo4j responds, False otherwise."""
    try:
        async with driver.session() as session:
            result = await session.run("RETURN 1 AS ok")
            await result.consume()
        return True
    except Exception as exc:
        logger.warning("Neo4j health check failed: %s", exc)
        return False


async def neo4j_upsert_node(driver: AsyncDriver, node: "GraphNode") -> None:  # type: ignore[name-defined]
    """MERGE a USE node in Neo4j. Logs and returns on any error."""
    try:
        props = {
            "id": str(node.id),
            "node_type": node.node_type,
            "canonical_id": node.canonical_id or "",
            "created_at": node.created_at.isoformat(),
            **{k: v for k, v in node.properties.items() if isinstance(v, (str, int, float, bool))},
        }
        async with driver.session() as session:
            await session.run(
                "MERGE (n:USE {id: $id}) SET n += $props",
                id=str(node.id),
                props=props,
            )
    except Exception as exc:
        logger.warning("Neo4j upsert_node failed for %s: %s", node.id, exc)


async def neo4j_create_edge(driver: AsyncDriver, edge: "GraphEdge") -> None:  # type: ignore[name-defined]
    """CREATE a relationship between two USE nodes. Logs and returns on any error."""
    try:
        async with driver.session() as session:
            await session.run(
                """
                MATCH (a:USE {id: $from_id}), (b:USE {id: $to_id})
                CREATE (a)-[r:EDGE {
                    id: $id,
                    edge_type: $edge_type,
                    layer: $layer,
                    confidence: $confidence
                }]->(b)
                """,
                from_id=str(edge.from_node_id),
                to_id=str(edge.to_node_id),
                id=str(edge.id),
                edge_type=edge.edge_type,
                layer=edge.layer,
                confidence=edge.confidence,
            )
    except Exception as exc:
        logger.warning("Neo4j create_edge failed for %s: %s", edge.id, exc)


async def neo4j_traverse(driver: AsyncDriver, from_id: str, depth: int) -> list[dict]:
    """
    Traverse outward from from_id up to depth hops.
    Returns list of {from_id, to_id, edge_type, layer} dicts.
    Returns empty list on any error.
    """
    try:
        async with driver.session() as session:
            result = await session.run(
                f"MATCH path = (n:USE {{id: $from_id}})-[*1..{depth}]->(m:USE) "
                "RETURN nodes(path) AS ns, relationships(path) AS rs",
                from_id=from_id,
            )
            rows = []
            async for record in result:
                rels = record["rs"]
                for rel in rels:
                    rows.append({
                        "from_id": str(rel.start_node.element_id),
                        "to_id": str(rel.end_node.element_id),
                        "edge_type": rel.get("edge_type", "RELATES_TO"),
                        "layer": rel.get("layer", "factual"),
                    })
            return rows
    except Exception as exc:
        logger.warning("Neo4j traverse failed from %s depth %d: %s", from_id, depth, exc)
        return []
