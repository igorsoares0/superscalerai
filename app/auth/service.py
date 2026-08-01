"""Password hashing (Argon2) and server-side session tokens."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.models import AuthSession, PasswordReset, User

_hasher = PasswordHasher()

# Argon2 bakes its cost parameters into the hash string, so verifying against
# this throwaway costs exactly what verifying a real user costs. Built once at
# import — hashing is deliberately slow.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """False when the password is wrong. `password_hash=None` means no such
    user, and still runs a full verification against a dummy hash: returning
    early there answers an unknown email measurably faster than a wrong
    password, which enumerates accounts no matter how careful the error
    message is."""
    try:
        verified = _hasher.verify(password_hash or _DUMMY_HASH, password)
    except VerificationError:
        return False
    return verified and password_hash is not None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user_id: str) -> str:
    """Returns the raw token (goes into the cookie); only its hash is stored."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    db.add(AuthSession(token_hash=_token_hash(token), user_id=user_id, expires_at=expires))
    return token


def user_from_token(db: Session, token: str) -> User | None:
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:  # SQLite returns naive datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        return None
    user = db.get(User, row.user_id)
    # deletion drops every session, but the row outlives the person (payments
    # are retained), so never hand it back as a logged-in user
    return None if user is None or user.deleted_at is not None else user


def revoke_session(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    db.commit()


def purge_expired_sessions(db: Session) -> None:
    now = datetime.now(timezone.utc)
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    db.execute(delete(PasswordReset).where(PasswordReset.expires_at < now))
    db.commit()


def create_password_reset(db: Session, user_id: str) -> str:
    """Returns the raw token (goes into the emailed link); only its hash is
    stored. Caller commits."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=settings.password_reset_ttl_minutes
    )
    db.add(PasswordReset(token_hash=_token_hash(token), user_id=user_id, expires_at=expires))
    return token


def reset_password(db: Session, token: str, new_password: str) -> User | None:
    """Consume a reset token: set the new password, revoke every login
    session (the old password may be compromised) and the user's other
    outstanding reset tokens. None when the token is unknown, used or
    expired. Caller commits."""
    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == _token_hash(token)))
    if row is None or row.used_at is not None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:  # SQLite returns naive datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        return None
    user = db.get(User, row.user_id)
    if user is None:
        return None
    user.password_hash = hash_password(new_password)
    row.used_at = datetime.now(timezone.utc)
    db.execute(
        delete(PasswordReset).where(
            PasswordReset.user_id == user.id, PasswordReset.id != row.id
        )
    )
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    return user
