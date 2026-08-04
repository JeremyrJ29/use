from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from use.api.v1._common import not_implemented
from use.models.graph import GraphEdge, GraphNode

router = APIRouter()


@router.get("/graph/entity/{entity_id}", response_model=None, status_code=501)
async def get_graph_entity(entity_id: str, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/graph/entity/{entity_id}/relationships", response_model=None, status_code=501)
async def get_entity_relationships(entity_id: str, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/graph/traverse", response_model=None, status_code=501)
async def traverse_graph(
    request: Request,
    from_id: str = Query(...),
    depth: int = Query(default=2, ge=1, le=10),
) -> JSONResponse:
    return not_implemented(request)


@router.get("/graph/gaps", response_model=None, status_code=501)
async def list_graph_gaps(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/graph/contradictions", response_model=None, status_code=501)
async def list_contradictions(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.post("/graph/confirm/{edge_id}", response_model=None, status_code=501)
async def confirm_graph_edge(edge_id: UUID, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/graph/summary", response_model=None, status_code=501)
async def graph_summary(request: Request) -> JSONResponse:
    return not_implemented(request)
