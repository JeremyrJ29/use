import logging

from fastapi import FastAPI

from use.api.router import api_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Universal Semantic Engine",
    description="Domain-agnostic, self-expanding semantic pipeline.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}

