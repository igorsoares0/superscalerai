import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import ratelimit
from app.api.deps import get_current_user
from app.auth import service
from app.core.config import settings
from app.database.models import User
from app.database.session import get_db
from app.services import account
from app.services import email as email_service

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

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
    return {
        "id": user.id,
        "email": user.email,
        "credits": user.credits,
        "email_verified": user.email_verified_at is not None,
    }


@router.post("/register", status_code=201)
def register(
    body: Credentials,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    # per-IP: rate limiting is now the SECOND line — the signup bonus waits for
    # a confirmed address — but a signup still costs us an outbound email
    ratelimit.enforce(
        f"register:ip:{ratelimit.client_ip(request)}",
        settings.register_rate_limit,
        settings.register_rate_window_minutes,
    )
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "email already registered")

    # credits=0 on purpose: the bonus is paid when the address is confirmed
    # (service.grant_signup_bonus). Everything else works meanwhile — an
    # unconfirmed account can look around, upload, and subscribe.
    user = User(email=email, password_hash=service.hash_password(body.password))
    db.add(user)
    db.flush()
    verification = service.create_email_verification(db, user.id)
    token = service.create_session(db, user.id)
    db.commit()
    background.add_task(
        email_service.send_verification,
        user.email,
        f"{settings.app_base_url}/verify?token={verification}",
    )
    _set_session_cookie(response, token)
    return _user_payload(user)


class VerifyBody(BaseModel):
    token: str = Field(min_length=16, max_length=128)


@router.post("/verify")
def verify_email(body: VerifyBody, response: Response, db: Session = Depends(get_db)) -> dict:
    """Consume a confirmation link. Signs the user in as well: the link is
    routinely opened in a different browser from the one that signed up."""
    user = service.verify_email(db, body.token)
    if user is None:
        raise HTTPException(400, "invalid or expired confirmation link")
    token = service.create_session(db, user.id)
    db.commit()
    logger.info("email confirmed for %s", user.id)
    _set_session_cookie(response, token)
    return _user_payload(user)


@router.post("/resend-verification")
def resend_verification(
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Issue a fresh confirmation link. Requires a session rather than an
    email in the body: that way it can't be turned into a way of mailing
    strangers, and it can't be used to probe which addresses exist."""
    if user.email_verified_at is not None:
        return {"ok": True}  # idempotent: nothing to confirm
    # per user; every hit sends a real email on our domain
    ratelimit.enforce(
        f"verify:user:{user.id}",
        settings.verify_resend_rate_limit,
        settings.verify_resend_rate_window_minutes,
    )
    verification = service.create_email_verification(db, user.id)
    db.commit()
    background.add_task(
        email_service.send_verification,
        user.email,
        f"{settings.app_base_url}/verify?token={verification}",
    )
    return {"ok": True}


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
    # same error AND same cost for unknown email and wrong password: the reply
    # must not leak which emails exist, by message or by response time
    verified = service.verify_password(user.password_hash if user else None, body.password)
    if user is None or not verified:
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


class DeleteBody(BaseModel):
    password: str = Field(min_length=8, max_length=128)


@router.post("/delete")
def delete_account(
    body: DeleteBody,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Erase the account. Irreversible, so it costs the password — a stolen
    session shouldn't be able to destroy someone's library and subscription."""
    if not service.verify_password(user.password_hash, body.password):
        raise HTTPException(401, "invalid credentials")
    try:
        keys = account.delete_account(db, user)
    except httpx.HTTPError:
        db.rollback()
        logger.exception("paddle cancel failed while deleting account %s", user.id)
        raise HTTPException(502, "couldn't cancel your subscription, nothing was deleted")
    db.commit()
    account.remove_files(keys)  # after the commit: orphan files beat orphan rows
    logger.info("account %s deleted", user.id)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


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
