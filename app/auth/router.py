"""Auth endpoints — placeholders until the SaaS-shell phase (see plan).

The vertical slice runs as a single dev user (app/api/deps.py).
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register() -> None:
    raise HTTPException(501, "not implemented yet")


@router.post("/login")
def login() -> None:
    raise HTTPException(501, "not implemented yet")


@router.post("/logout")
def logout() -> None:
    raise HTTPException(501, "not implemented yet")
