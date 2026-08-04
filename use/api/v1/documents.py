from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from use.api.v1._common import not_implemented
from use.models.lakehouse import LakehouseRecord

router = APIRouter()


@router.get("/documents", response_model=None, status_code=501)
async def list_documents(
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
) -> JSONResponse:
    return not_implemented(request)


@router.get("/documents/search", response_model=None, status_code=501)
async def search_documents(
    request: Request,
    q: str = Query(..., min_length=1),
) -> JSONResponse:
    return not_implemented(request)


@router.get("/documents/{doc_id}", response_model=None, status_code=501)
async def get_document(doc_id: UUID, request: Request) -> JSONResponse:
    return not_implemented(request)
