from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from use.api.v1._common import not_implemented

router = APIRouter()


@router.get("/patterns", response_model=None, status_code=501)
async def list_patterns(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/patterns/entity/{entity_id}", response_model=None, status_code=501)
async def entity_patterns(entity_id: str, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/anomalies", response_model=None, status_code=501)
async def list_anomalies(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.post("/anomalies/{anomaly_id}/acknowledge", response_model=None, status_code=501)
async def acknowledge_anomaly(anomaly_id: UUID, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/gaps", response_model=None, status_code=501)
async def list_gaps(request: Request) -> JSONResponse:
    return not_implemented(request)
