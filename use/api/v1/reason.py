from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from use.api.v1._common import not_implemented

router = APIRouter()


class ReasonRequest(BaseModel):
    query: str
    context: dict[str, Any] | None = None
    use_llm: bool = False


@router.post("/reason", response_model=None, status_code=501)
async def create_reason_task(body: ReasonRequest, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/reason/{task_id}/status", response_model=None, status_code=501)
async def get_reason_status(task_id: UUID, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/reason/{task_id}/result", response_model=None, status_code=501)
async def get_reason_result(task_id: UUID, request: Request) -> JSONResponse:
    return not_implemented(request)
