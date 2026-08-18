"""HTML pages (Jinja2). Auth is enforced client-side: pages are static
shells, app.js calls /auth/me and redirects to /login on 401."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import settings
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
        {
            "id": key,
            "label": PRESET_LABELS[key][0],
            "hint": PRESET_LABELS[key][1],
            "creativity": PRESETS[key].denoise,
            "resemblance": PRESETS[key].guidance,
            "hdr": PRESETS[key].hdr,
        }
        for key in PRESETS
    ]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "presets": presets,
            "page": "workspace",
            "max_upload_mb": settings.max_upload_mb,
            "max_image_px": settings.max_image_px,
        },
    )


@router.get("/library", response_class=HTMLResponse)
def library(request: Request):
    return templates.TemplateResponse(request, "library.html", {"page": "library"})


@router.get("/login", response_class=HTMLResponse)
def login(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"page": "login", "signup_bonus_credits": settings.signup_bonus_credits},
    )


@router.get("/reset", response_class=HTMLResponse)
def reset(request: Request):
    """Landing page for the password-reset email link (?token=...)."""
    return templates.TemplateResponse(request, "reset.html", {"page": "reset"})


@router.get("/verify", response_class=HTMLResponse)
def verify(request: Request):
    """Landing page for the confirmation email link (?token=...), and the
    holding page for a signed-in account that hasn't confirmed yet — app.js
    sends those here instead of rendering a workspace they can't use.

    Renders standalone rather than from base.html: the link is routinely
    opened in a browser with no session, and base.html's app.js would bounce
    it to /login before the token was ever spent."""
    return templates.TemplateResponse(
        request,
        "verify.html",
        {"page": "verify", "signup_bonus_credits": settings.signup_bonus_credits},
    )


# Bump when the wording of any of the three pages changes: it is what a
# customer (and Paddle's reviewer) reads as the version they agreed to.
LEGAL_UPDATED = "5 August 2026"


def _legal_page(request: Request, template: str) -> HTMLResponse:
    """The three public policy pages. Paddle requires all of them to be
    reachable without an account during approval, which is why they render
    from legal.html instead of base.html — base.html loads app.js, which
    bounces anyone without a session to /login."""
    return templates.TemplateResponse(
        request,
        template,
        {
            "page": "legal",
            "updated": LEGAL_UPDATED,
            "legal": {
                "entity": settings.legal_entity,
                "address": settings.legal_address,
                "contact_email": settings.legal_contact_email,
                "governing_law": settings.legal_governing_law,
            },
            "window_days": settings.refund_window_days,
        },
    )


@router.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    return _legal_page(request, "terms.html")


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return _legal_page(request, "privacy.html")


@router.get("/refunds", response_class=HTMLResponse)
def refunds(request: Request):
    return _legal_page(request, "refunds.html")
