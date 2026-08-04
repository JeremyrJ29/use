from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from use.api.v1._common import not_implemented
from use.models.catalog import CatalogEntry

router = APIRouter()


@router.get("/catalog", response_model=None, status_code=501)
async def list_catalog(
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
) -> JSONResponse:
    return not_implemented(request)


@router.get("/catalog/search", response_model=None, status_code=501)
async def search_catalog(
    request: Request,
    q: str = Query(..., min_length=1),
) -> JSONResponse:
    return not_implemented(request)


@router.get("/catalog/{canonical_id}", response_model=None, status_code=501)
async def get_catalog_entry(canonical_id: str, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.post("/catalog/{canonical_id}/confirm", response_model=None, status_code=501)
async def confirm_catalog_entry(canonical_id: str, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/catalog/{id}/documents", response_model=None, status_code=501)
async def catalog_documents(id: str, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/catalog/{id}/relationships", response_model=None, status_code=501)
async def catalog_relationships(id: str, request: Request) -> JSONResponse:
    return not_implemented(request)
