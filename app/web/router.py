"""HTML pages (Jinja2). Auth is enforced client-side: pages are static
shells, app.js calls /auth/me and redirects to /login on 401."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.pipeline.presets import PRESETS

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

router = APIRouter(include_in_schema=False)

PRESET_LABELS = {
    "portrait": ("Portrait", "People and faces"),
    "product": ("Product", "Packshots, labels and logos"),
    "architecture": ("Architecture", "Buildings and interiors"),
    "ai-generated": ("AI art", "Generated images, more creative"),
}


@router.get("/", response_class=HTMLResponse)
def workspace(request: Request):
    presets = [
        {"id": key, "label": PRESET_LABELS[key][0], "hint": PRESET_LABELS[key][1]}
        for key in PRESETS
    ]
    return templates.TemplateResponse(
        request, "index.html", {"presets": presets, "page": "workspace"}
    )


@router.get("/library", response_class=HTMLResponse)
def library(request: Request):
    return templates.TemplateResponse(request, "library.html", {"page": "library"})


@router.get("/login", response_class=HTMLResponse)
def login(request: Request):
    return templates.TemplateResponse(request, "login.html", {"page": "login"})
