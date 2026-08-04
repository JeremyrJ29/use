from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from use.api.v1._common import not_implemented
from use.models.dict import DictEntry, OntologyEntry

router = APIRouter()


@router.get("/dict/lookup", response_model=None, status_code=501)
async def dict_lookup(
    request: Request,
    q: str = Query(..., min_length=1),
    domain: str | None = Query(default=None),
) -> JSONResponse:
    return not_implemented(request)


@router.get("/dict/entry/{entry_id}", response_model=None, status_code=501)
async def get_dict_entry(entry_id: UUID, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.post("/dict/entry", response_model=None, status_code=501)
async def create_dict_entry(body: DictEntry, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.put("/dict/entry/{entry_id}", response_model=None, status_code=501)
async def update_dict_entry(entry_id: UUID, body: DictEntry, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.post("/dict/merge", response_model=None, status_code=501)
async def merge_dict_entries(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/dict/pending", response_model=None, status_code=501)
async def list_pending_dict(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.post("/dict/approve/{entry_id}", response_model=None, status_code=501)
async def approve_dict_entry(entry_id: UUID, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/ontology", response_model=None, status_code=501)
async def list_ontology(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.post("/ontology/entry", response_model=None, status_code=501)
async def create_ontology_entry(body: OntologyEntry, request: Request) -> JSONResponse:
    return not_implemented(request)
