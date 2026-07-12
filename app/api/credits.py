from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.models import CreditLedger, User
from app.database.session import get_db

router = APIRouter(prefix="/credits", tags=["credits"])


@router.get("")
def get_credits(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    rows = db.scalars(
        select(CreditLedger)
        .where(CreditLedger.user_id == user.id)
        .order_by(CreditLedger.created_at.desc())
        .limit(50)
    )
    return {
        "balance": user.credits,
        "ledger": [
            {
                "delta": e.delta,
                "reason": e.reason,
                "job_id": e.job_id,
                "created_at": e.created_at.isoformat(),
            }
            for e in rows
        ],
    }
