from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.models import ImageRecord, User
from app.database.session import get_db

router = APIRouter(prefix="/download", tags=["download"])


def _owned_image(image_id: str, db: Session, user: User) -> ImageRecord:
    image = db.get(ImageRecord, image_id)
    if image is None or image.user_id != user.id:
        raise HTTPException(404, "image not found")
    return image


@router.get("/{image_id}")
def download(
    image_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> FileResponse:
    image = _owned_image(image_id, db, user)
    if image.enhanced_path is None:
        raise HTTPException(409, "image not enhanced yet")
    return FileResponse(image.enhanced_path, filename="enhanced.png")


@router.get("/{image_id}/original")
def download_original(
    image_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> FileResponse:
    image = _owned_image(image_id, db, user)
    return FileResponse(image.original_path)


@router.get("/{image_id}/thumb")
def download_thumb(
    image_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> FileResponse:
    image = _owned_image(image_id, db, user)
    return FileResponse(image.thumb_path or image.original_path)
