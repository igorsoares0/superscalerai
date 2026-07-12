"""Credit accounting: atomic debit on job creation, idempotent refund on failure.

Every movement writes a CreditLedger row AND updates the denormalized
users.credits balance in the same transaction — callers commit.
"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database.models import CreditLedger, Job, User


class InsufficientCredits(Exception):
    pass


def job_cost(width: int, height: int, scale_factor: float = 2) -> int:
    """Cost by output resolution (SPEC.md Credits table)."""
    long_edge = max(width, height) * scale_factor
    if long_edge <= 1024:
        return 1
    if long_edge <= 2048:
        return 2
    return 4


def debit_for_job(db: Session, user: User, job: Job, cost: int) -> None:
    """Conditional UPDATE so concurrent requests can never spend the same
    credits twice; raises InsufficientCredits when the balance is short."""
    result = db.execute(
        update(User)
        .where(User.id == user.id, User.credits >= cost)
        .values(credits=User.credits - cost)
    )
    if result.rowcount == 0:
        raise InsufficientCredits(f"job needs {cost} credits")
    job.credits_cost = cost
    db.add(CreditLedger(user_id=user.id, delta=-cost, reason="job_debit", job_id=job.id))


def refund_job(db: Session, job: Job) -> bool:
    """Return the job's credits to its owner. Idempotent: a job that already
    has a refund ledger entry is never refunded twice."""
    if job.credits_cost <= 0:
        return False
    already = db.scalar(
        select(CreditLedger.id).where(
            CreditLedger.job_id == job.id, CreditLedger.reason == "job_refund"
        )
    )
    if already is not None:
        return False
    db.execute(
        update(User).where(User.id == job.user_id).values(credits=User.credits + job.credits_cost)
    )
    db.add(
        CreditLedger(
            user_id=job.user_id, delta=job.credits_cost, reason="job_refund", job_id=job.id
        )
    )
    return True
