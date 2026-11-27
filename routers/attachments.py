from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import MessageAttachment
from services.auth import AuthContext, require_auth
from services.media import is_inline_safe, resolve_media_path

router = APIRouter()


@router.get("/{attachment_id}")
def get_attachment(
    attachment_id: int,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    att = (
        db.query(MessageAttachment)
        .options(joinedload(MessageAttachment.message))
        .filter(MessageAttachment.id == attachment_id)
        .first()
    )
    if not att or not att.message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")

    if att.message.deleted_at is not None and auth.user.role != "admin":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")

    try:
        file_path = resolve_media_path(att.storage_key)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")

    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment file missing on disk.")

    disp_type = "inline" if is_inline_safe(att.content_type) else "attachment"
    safe_name = (att.original_filename or file_path.name).replace('"', "")

    return FileResponse(
        path=str(file_path),
        media_type=att.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'{disp_type}; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store, no-cache, must-revalidate",
        },
    )
