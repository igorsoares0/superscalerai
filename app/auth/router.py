from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.auth import service
from app.core.config import settings
from app.database.models import CreditLedger, User
from app.database.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = "session"


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


def _user_payload(user: User) -> dict:
    return {"id": user.id, "email": user.email, "credits": user.credits}


@router.post("/register", status_code=201)
def register(body: Credentials, response: Response, db: Session = Depends(get_db)) -> dict:
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "email already registered")

    user = User(
        email=email,
        password_hash=service.hash_password(body.password),
        credits=settings.signup_bonus_credits,
    )
    db.add(user)
    db.flush()
    if settings.signup_bonus_credits > 0:
        db.add(
            CreditLedger(
                user_id=user.id, delta=settings.signup_bonus_credits, reason="signup_bonus"
            )
        )
    token = service.create_session(db, user.id)
    db.commit()
    _set_session_cookie(response, token)
    return _user_payload(user)


@router.post("/login")
def login(body: Credentials, response: Response, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    # same error for unknown email and wrong password: don't leak which emails exist
    if user is None or not service.verify_password(user.password_hash, body.password):
        raise HTTPException(401, "invalid credentials")
    token = service.create_session(db, user.id)
    db.commit()
    _set_session_cookie(response, token)
    return _user_payload(user)


@router.post("/logout")
def logout(
    response: Response,
    session: str | None = Cookie(None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> dict:
    if session:
        service.revoke_session(db, session)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return _user_payload(user)
