"""Shared API dependencies.

Auth is not implemented yet (vertical-slice phase): every request runs as
a single dev user, created on first use. Replace with real session auth.
"""

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import User
from app.database.session import get_db

DEV_EMAIL = "dev@localhost"


def get_current_user(db: Session = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.email == DEV_EMAIL))
    if user is None:
        user = User(email=DEV_EMAIL, password_hash="!dev", credits=1000)
        db.add(user)
        db.commit()
    return user
