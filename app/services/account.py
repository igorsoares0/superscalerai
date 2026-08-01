"""Account deletion: erase the person, keep the money trail.

`payments` has to be retained for tax purposes and `credit_ledger` is the
append-only financial history; both carry a foreign key to `users.id`. So the
user row survives, scrubbed of everything that identifies a person, instead of
cascading away and taking the accounting with it.

Order matters. The subscription is canceled at Paddle FIRST, and a failure
there aborts the whole thing: deleting locally while the card keeps being
charged is the worst outcome available — the webhook would arrive to an
account that no longer claims the subscription and be ignored.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.database.models import (
    AuthSession,
    CreditLedger,
    ImageRecord,
    Job,
    PasswordReset,
    User,
)
from app.services import billing, storage

logger = logging.getLogger(__name__)

DELETED_EMAIL_DOMAIN = "deleted.invalid"  # RFC 2606: can never be a real address


def delete_account(db: Session, user: User) -> list[str]:
    """Cancel billing, drop the user's content, scrub the row. Returns the
    storage keys to remove — the caller deletes them AFTER the commit, so a
    crash leaves orphan files (harmless) instead of rows pointing at nothing.

    Raises httpx.HTTPError if Paddle can't be reached; nothing is committed."""
    if user.paddle_subscription_id:
        # immediately, not end-of-period: they're asking to be gone now, and an
        # account that can't log in must not keep being billed
        billing.cancel_subscription(user.paddle_subscription_id, immediately=True)

    images = db.scalars(select(ImageRecord).where(ImageRecord.user_id == user.id)).all()
    keys = [k for row in images for k in (row.original_path, row.enhanced_path, row.thumb_path) if k]

    job_ids = db.scalars(select(Job.id).where(Job.user_id == user.id)).all()
    if job_ids:
        # the ledger is financial history: orphan its job references, never
        # delete the entries (same rule as DELETE /images/{id})
        db.execute(update(CreditLedger).where(CreditLedger.job_id.in_(job_ids)).values(job_id=None))
        db.execute(delete(Job).where(Job.id.in_(job_ids)))
    db.execute(delete(ImageRecord).where(ImageRecord.user_id == user.id))
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))

    if user.credits > 0:  # balance and ledger are always written together
        db.add(CreditLedger(user_id=user.id, delta=-user.credits, reason="account_deleted"))
        user.credits = 0
    # the address is freed so the person can sign up again, and the hash is
    # replaced with a value no password can ever verify against
    user.email = f"deleted+{user.id}@{DELETED_EMAIL_DOMAIN}"
    user.password_hash = ""
    user.plan = None
    user.paddle_subscription_id = None
    user.plan_renews_at = None
    user.plan_cancels_at = None
    user.plan_pending = None
    user.deleted_at = datetime.now(timezone.utc)
    return keys


def remove_files(keys: list[str]) -> None:
    """Best effort, post-commit: a file we fail to delete is a leak to clean up
    later, not a reason to fail a deletion that already happened."""
    for key in keys:
        try:
            storage.get_storage().delete(key)
        except Exception:  # noqa: BLE001 — the account is already gone
            logger.warning("couldn't remove file %s of a deleted account", key)
