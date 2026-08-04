from fastapi import APIRouter

from use.api.v1 import (
    ingest,
    documents,
    catalog,
    dict as dict_router,
    graph,
    patterns,
    review,
    reason,
    health,
    improvement,
)
from use.api.v1.auth_dev import router as auth_router
from use.api.v1 import ui as ui_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(ui_router.router, tags=["ui"])
api_router.include_router(ingest.router, prefix="/api/v1", tags=["ingestion"])
api_router.include_router(documents.router, prefix="/api/v1", tags=["documents"])
api_router.include_router(catalog.router, prefix="/api/v1", tags=["catalog"])
api_router.include_router(dict_router.router, prefix="/api/v1", tags=["dict"])
api_router.include_router(graph.router, prefix="/api/v1", tags=["graph"])
api_router.include_router(patterns.router, prefix="/api/v1", tags=["patterns"])
api_router.include_router(review.router, prefix="/api/v1", tags=["review"])
api_router.include_router(reason.router, prefix="/api/v1", tags=["reason"])
api_router.include_router(health.router, prefix="/api/v1", tags=["health"])
api_router.include_router(improvement.router, prefix="/api/v1", tags=["improvement"])

