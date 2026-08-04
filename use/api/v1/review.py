from __future__ import annotations

from uuid import UUID
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from use.api.v1._common import not_implemented
from use.models.review import ReviewItem

router = APIRouter()


class ReviewUpdateBody(BaseModel):
    notes: str | None = None
    payload: dict[str, Any] | None = None


@router.get("/review", response_model=None, status_code=501)
async def list_all_review(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/review/dict", response_model=None, status_code=501)
async def review_dict_queue(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/review/graph", response_model=None, status_code=501)
async def review_graph_queue(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/review/anomalies", response_model=None, status_code=501)
async def review_anomalies_queue(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.get("/review/gaps", response_model=None, status_code=501)
async def review_gaps_queue(request: Request) -> JSONResponse:
    return not_implemented(request)


@router.post("/review/{review_id}/approve", response_model=None, status_code=501)
async def approve_review_item(review_id: UUID, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.post("/review/{review_id}/reject", response_model=None, status_code=501)
async def reject_review_item(review_id: UUID, request: Request) -> JSONResponse:
    return not_implemented(request)


@router.put("/review/{review_id}", response_model=None, status_code=501)
async def update_review_item(review_id: UUID, body: ReviewUpdateBody, request: Request) -> JSONResponse:
    return not_implemented(request)
