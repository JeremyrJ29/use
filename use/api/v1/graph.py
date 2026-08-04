from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from use.db.postgres import get_db
from use.services import graph_service

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /graph/entity/{entity_id}
# ---------------------------------------------------------------------------

@router.get("/graph/entity/{entity_id}", response_model=None)
async def get_graph_entity(
    entity_id: str,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    node = await graph_service.get_entity_node(entity_id, db)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

    edges = await graph_service.get_node_relationships(str(node.id), None, db)

    edge_list = []
    for edge in edges:
        other_id = str(edge.to_node_id) if str(edge.from_node_id) == str(node.id) else str(edge.from_node_id)
        other_node = await graph_service.get_entity_node(other_id, db)
        edge_list.append({
            "id": str(edge.id),
            "edge_type": edge.edge_type,
            "layer": edge.layer,
            "confidence": edge.confidence,
            "to_node": {
                "id": other_id,
                "canonical_id": other_node.canonical_id if other_node else None,
                "node_type": other_node.node_type if other_node else None,
            },
        })

    return JSONResponse({
        "node": {
            "id": str(node.id),
            "node_type": node.node_type,
            "canonical_id": node.canonical_id,
            "properties": node.properties,
        },
        "edges": edge_list,
    })


# ---------------------------------------------------------------------------
# GET /graph/entity/{entity_id}/relationships
# ---------------------------------------------------------------------------

@router.get("/graph/entity/{entity_id}/relationships", response_model=None)
async def get_entity_relationships(
    entity_id: str,
    layer: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    node = await graph_service.get_entity_node(entity_id, db)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found")

    edges = await graph_service.get_node_relationships(str(node.id), layer, db)
    return JSONResponse({
        "node_id": str(node.id),
        "canonical_id": node.canonical_id,
        "layer_filter": layer,
        "edges": [
            {
                "id": str(e.id),
                "from_node_id": str(e.from_node_id),
                "to_node_id": str(e.to_node_id),
                "edge_type": e.edge_type,
                "layer": e.layer,
                "confidence": e.confidence,
                "properties": e.properties,
            }
            for e in edges
        ],
    })


# ---------------------------------------------------------------------------
# GET /graph/traverse
# ---------------------------------------------------------------------------

@router.get("/graph/traverse", response_model=None)
async def traverse_graph(
    from_id: str = Query(...),
    depth: int = Query(default=2, ge=1, le=4),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # Try Neo4j first
    try:
        from use.db.neo4j import get_driver, neo4j_traverse
        driver = get_driver()
        neo4j_rows = await neo4j_traverse(driver, from_id, depth)
        if neo4j_rows:
            adjacency: dict = {}
            for row in neo4j_rows:
                fn = row["from_id"]
                if fn not in adjacency:
                    adjacency[fn] = {"edges": []}
                adjacency[fn]["edges"].append({
                    "to_id": row["to_id"],
                    "edge_type": row["edge_type"],
                    "layer": row["layer"],
                })
            return JSONResponse({"source": "neo4j", "graph": adjacency})
    except Exception:
        pass

    # Fallback: Postgres recursive CTE
    adjacency = await graph_service.traverse(from_id, depth, db)
    return JSONResponse({"source": "postgres", "graph": adjacency})


# ---------------------------------------------------------------------------
# GET /graph/gaps
# ---------------------------------------------------------------------------

@router.get("/graph/gaps", response_model=None)
async def list_graph_gaps(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    edges = await graph_service.get_gaps(db)
    return JSONResponse({
        "gaps": [
            {
                "id": str(e.id),
                "from_node_id": str(e.from_node_id),
                "to_node_id": str(e.to_node_id),
                "layer": e.layer,
                "confidence": e.confidence,
                "properties": e.properties,
                "acknowledged": e.acknowledged,
            }
            for e in edges
        ]
    })


# ---------------------------------------------------------------------------
# GET /graph/contradictions
# ---------------------------------------------------------------------------

@router.get("/graph/contradictions", response_model=None)
async def list_contradictions(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    edges = await graph_service.get_contradictions(db)
    return JSONResponse({
        "contradictions": [
            {
                "id": str(e.id),
                "from_node_id": str(e.from_node_id),
                "to_node_id": str(e.to_node_id),
                "layer": e.layer,
                "confidence": e.confidence,
                "properties": e.properties,
                "acknowledged": e.acknowledged,
            }
            for e in edges
        ]
    })


# ---------------------------------------------------------------------------
# POST /graph/confirm/{edge_id}
# ---------------------------------------------------------------------------

@router.post("/graph/confirm/{edge_id}", response_model=None)
async def confirm_graph_edge(
    edge_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    reviewer_id = getattr(request.state, "user_id", "anonymous")
    try:
        async with db.begin():
            edge = await graph_service.confirm_edge(str(edge_id), reviewer_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return JSONResponse({
        "id": str(edge.id),
        "edge_type": edge.edge_type,
        "layer": edge.layer,
        "confidence": edge.confidence,
    })


# ---------------------------------------------------------------------------
# GET /graph/summary
# ---------------------------------------------------------------------------

@router.get("/graph/summary", response_model=None)
async def graph_summary(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    summary = await graph_service.get_graph_summary(db)
    return JSONResponse(summary)
