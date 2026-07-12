import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.database.models import ImageRecord, User
from app.database.session import get_db

router = APIRouter(prefix="/images", tags=["images"])

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


@router.post("/upload", status_code=201)
async def upload_image(
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
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

    ext = image.format.lower()
    dest = Path(settings.storage_dir) / "uploads" / f"{uuid.uuid4()}.{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    width, height = Image.open(dest).size
    row = ImageRecord(
        user_id=user.id, original_path=str(dest), width=width, height=height
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
