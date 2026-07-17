from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.models import ImageRecord, User
from app.database.session import get_db
from app.services.storage import get_storage, media_type_for

router = APIRouter(prefix="/download", tags=["download"])


def _owned_image(image_id: str, db: Session, user: User) -> ImageRecord:
    image = db.get(ImageRecord, image_id)
    if image is None or image.user_id != user.id:
        raise HTTPException(404, "image not found")
    return image


def _serve(key: str, download_name: str | None = None) -> Response:
    try:
        data = get_storage().get(key)
    except FileNotFoundError:
        raise HTTPException(404, "file missing from storage") from None
    headers = {}
    if download_name:
        headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
    return Response(data, media_type=media_type_for(key), headers=headers)


@router.get("/{image_id}")
def download(
    image_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    image = _owned_image(image_id, db, user)
    if image.enhanced_path is None:
        raise HTTPException(409, "image not enhanced yet")
    return _serve(image.enhanced_path, download_name="enhanced.png")


@router.get("/{image_id}/original")
def download_original(
    image_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    image = _owned_image(image_id, db, user)
    return _serve(image.original_path)


@router.get("/{image_id}/thumb")
def download_thumb(
    image_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Response:
    image = _owned_image(image_id, db, user)
    return _serve(image.thumb_path or image.original_path)
