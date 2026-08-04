"""UI routes — serve Jinja2 templates for the Human Review Gate."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/ui/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/ui/review", response_class=HTMLResponse, include_in_schema=False)
async def review(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("review.html", {"request": request})


@router.get("/ui/catalog", response_class=HTMLResponse, include_in_schema=False)
async def catalog(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("catalog.html", {"request": request})


@router.get("/ui/anomalies", response_class=HTMLResponse, include_in_schema=False)
async def anomalies(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("anomalies.html", {"request": request})


@router.get("/ui/patterns", response_class=HTMLResponse, include_in_schema=False)
async def patterns(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("patterns.html", {"request": request})
