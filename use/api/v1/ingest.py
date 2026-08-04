from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from use.api.v1._common import not_implemented
from use.models.ingestion import IngestionRecord, IngestionStatus

router = APIRouter()


@router.post("/ingest", response_model=None, status_code=501)
async def ingest_record(body: IngestionRecord, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/ingest/{record_id}/status", response_model=None, status_code=501)
async def get_ingest_status(record_id: UUID, request: Request) -> JSONResponse:
    return not_implemented(request)
