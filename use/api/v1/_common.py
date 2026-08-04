from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


def not_implemented(request: Request) -> JSONResponse:
    method = request.method
    path = request.url.path
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented", "route": f"{method} {path}"},
    )


class NotImplementedResponse(dict):
    """Placeholder response schema for 501 routes."""
    status: str
    route: str
