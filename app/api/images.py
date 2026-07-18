import io
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.api import ratelimit
from app.api.deps import get_current_user
from app.core.config import settings
from app.database.models import CreditLedger, ImageRecord, Job, User
from app.database.session import get_db
from app.services import storage

router = APIRouter(prefix="/images", tags=["images"])
logger = logging.getLogger(__name__)

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


@router.post("/upload", status_code=201)
async def upload_image(
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    ratelimit.enforce(
        f"upload:user:{user.id}",
        settings.upload_rate_limit,
        settings.upload_rate_window_minutes,
    )
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"file exceeds {settings.max_upload_mb}MB")
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
    except UnidentifiedImageError:
        raise HTTPException(415, "not a valid image") from None
    if image.format not in ALLOWED_FORMATS:
        raise HTTPException(415, f"format {image.format} not supported")
    width, height = image.size
    if max(width, height) > settings.max_image_px:
        raise HTTPException(
            413,
            f"image is {width}×{height}px; the longest side must be "
            f"at most {settings.max_image_px}px",
        )

    ext = image.format.lower()
    key = f"uploads/{uuid.uuid4()}.{ext}"
    storage.get_storage().put(key, data)
    row = ImageRecord(
        user_id=user.id, original_path=key, width=width, height=height
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "width": width, "height": height}


@router.get("/{image_id}")
def get_image(
    image_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    row = db.get(ImageRecord, image_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "image not found")
    return {
        "id": row.id,
        "width": row.width,
        "height": row.height,
        "enhanced": row.enhanced_path is not None,
    }


@router.delete("/{image_id}")
def delete_image(
    image_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    row = db.get(ImageRecord, image_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "image not found")
    active = db.scalar(
        select(Job.id).where(
            Job.image_id == row.id, Job.status.in_(("pending", "queued", "running"))
        )
    )
    if active is not None:
        raise HTTPException(409, "a job is still processing this image")

    job_ids = db.scalars(select(Job.id).where(Job.image_id == row.id)).all()
    if job_ids:
        # the credit ledger is the financial history — orphan its job
        # references, never delete the entries themselves
        db.execute(
            update(CreditLedger).where(CreditLedger.job_id.in_(job_ids)).values(job_id=None)
        )
        db.execute(delete(Job).where(Job.id.in_(job_ids)))
    keys = [row.original_path, row.enhanced_path, row.thumb_path]
    db.delete(row)
    db.commit()

    # files go last: a crash above leaves them orphaned in storage (harmless),
    # never a DB row pointing at nothing
    for key in keys:
        if key:
            try:
                storage.get_storage().delete(key)
            except Exception:  # noqa: BLE001 — best effort, row is already gone
                logger.warning("couldn't remove file %s", key)
    return {"ok": True}


@router.get("")
def list_images(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    rows = db.scalars(
        select(ImageRecord).where(ImageRecord.user_id == user.id).order_by(ImageRecord.created_at.desc())
    )
    return [
        {"id": r.id, "width": r.width, "height": r.height, "enhanced": r.enhanced_path is not None}
        for r in rows
    ]
