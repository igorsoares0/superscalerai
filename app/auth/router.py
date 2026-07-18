from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import ratelimit
from app.api.deps import get_current_user
from app.auth import service
from app.core.config import settings
from app.database.models import CreditLedger, User
from app.database.session import get_db
from app.services import email as email_service

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
def register(
    body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict:
    # per-IP: every account mints signup_bonus_credits, which are paid GPU time
    ratelimit.enforce(
        f"register:ip:{ratelimit.client_ip(request)}",
        settings.register_rate_limit,
        settings.register_rate_window_minutes,
    )
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
def login(
    body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict:
    email = body.email.lower()
    # per-IP and per-email: one attacker can't brute-force many accounts, and
    # many machines can't brute-force one account
    for key in (f"login:ip:{ratelimit.client_ip(request)}", f"login:email:{email}"):
        ratelimit.enforce(key, settings.login_rate_limit, settings.login_rate_window_minutes)
    user = db.scalar(select(User).where(User.email == email))
    # same error for unknown email and wrong password: don't leak which emails exist
    if user is None or not service.verify_password(user.password_hash, body.password):
        raise HTTPException(401, "invalid credentials")
    # correct password: forget the attempt history so a legit user who fumbled
    # their password a few times isn't locked out of their own account
    ratelimit.limiter.clear(f"login:email:{email}")
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


class ForgotBody(BaseModel):
    email: EmailStr


class ResetBody(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    password: str = Field(min_length=8, max_length=128)


@router.post("/forgot")
def forgot_password(
    body: ForgotBody,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    email = body.email.lower()
    # per-IP and per-email: every hit can send a real email on our domain
    for key in (f"forgot:ip:{ratelimit.client_ip(request)}", f"forgot:email:{email}"):
        ratelimit.enforce(key, settings.forgot_rate_limit, settings.forgot_rate_window_minutes)
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        token = service.create_password_reset(db, user.id)
        db.commit()
        reset_url = f"{settings.app_base_url}/reset?token={token}"
        # sent after the response so timing doesn't reveal whether the email exists
        background.add_task(email_service.send_password_reset, user.email, reset_url)
    # same answer for known and unknown emails: don't leak which ones exist
    return {"ok": True}


@router.post("/reset")
def reset_password(body: ResetBody, response: Response, db: Session = Depends(get_db)) -> dict:
    user = service.reset_password(db, body.token, body.password)
    if user is None:
        raise HTTPException(400, "invalid or expired reset link")
    # reset_password revoked every session; sign the user straight in here
    token = service.create_session(db, user.id)
    db.commit()
    _set_session_cookie(response, token)
    return _user_payload(user)
