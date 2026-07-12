"""Shared API dependencies."""

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import service
from app.database.models import User
from app.database.session import get_db


def get_current_user(
    session: str | None = Cookie(None, alias="session"),
    db: Session = Depends(get_db),
) -> User:
    if session:
        user = service.user_from_token(db, session)
        if user is not None:
            return user
    raise HTTPException(401, "not authenticated")
