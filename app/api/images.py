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
from app.services import credits, storage

router = APIRouter(prefix="/images", tags=["images"])
logger = logging.getLogger(__name__)

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
READ_CHUNK = 256 * 1024


async def _read_within_limit(file: UploadFile, limit: int) -> bytes:
    """The whole request is already capped by BodySizeLimitMiddleware; this
    enforces the documented per-file limit exactly, and stops assembling the
    bytes the moment the file goes over instead of after."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(READ_CHUNK):
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"file exceeds {settings.max_upload_mb}MB")
        chunks.append(chunk)
    return b"".join(chunks)


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
    # An upload that can never become a job is pure storage cost, so the two
    # conditions that make it impossible are checked BEFORE reading the body:
    # nothing is spooled, nothing is stored, and the user hears the real
    # reason instead of hitting a 402 one screen later.
    if user.email_verified_at is None:
        raise HTTPException(403, "confirm your email address before uploading")
    if user.credits <= 0:
        raise HTTPException(402, "you're out of credits — top up to upload again")
    data = await _read_within_limit(file, settings.max_upload_mb * 1024 * 1024)
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
    except Image.DecompressionBombError:
        # So many pixels PIL refuses to even decode the header — a 227 KB PNG
        # can declare 20000x12000. It's the same answer as the max_image_px
        # check below, which is what it would have failed anyway.
        raise HTTPException(
            413,
            f"image is too large; the longest side must be "
            f"at most {settings.max_image_px}px",
        ) from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        # UnidentifiedImageError alone isn't enough: a truncated PNG raises a
        # plain OSError, and a malformed header can surface as either of the
        # others. Uncaught, all of them were a 500 on a request anyone can
        # make for free.
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

    # Jobs always run at 2x, so the cost of THIS image is already decided —
    # storing one the balance can't upscale wastes the same bytes as the
    # zero-credit case above, just less obviously.
    cost = credits.job_cost(width, height)
    if user.credits < cost:
        raise HTTPException(
            402,
            f"upscaling this image costs {cost} credits and you have "
            f"{user.credits} — top up, or upload a smaller image",
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
