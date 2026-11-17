from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import re
from pydantic import BaseModel

from database import get_db
import models, schemas
from services.broadcaster import broadcaster

router = APIRouter()


class MarkReadPayload(BaseModel):
    phone: str


def get_phone_variants(phone: str) -> List[str]:
    """Returns likely stored phone string representations for matching legacy and E.164 rows."""
    raw = phone.strip()
    clean = re.sub(r"\D", "", raw)
    variants = [raw]

    if clean:
        if len(clean) == 11 and clean.startswith("1"):
            base10 = clean[1:]
            variants.extend([f"+1{base10}", f"1{base10}", base10])
        elif len(clean) == 10:
            variants.extend([f"+1{clean}", f"1{clean}", clean])
        else:
            variants.extend([f"+{clean}", clean])

    # Preserve order while deduplicating
    return list(dict.fromkeys(v for v in variants if v))


@router.get("/", response_model=List[schemas.MessageResponse])
def get_messages(
    sender: Optional[str] = None,
    recipient: Optional[str] = None,
    from_datetime: Optional[datetime] = None,
    to_datetime: Optional[datetime] = None,
    limit: int = Query(500, le=2000),
    db: Session = Depends(get_db)
):
    """
    Fetches message history for the web UI. 
    Allows filtering by sender/recipient to build specific chat threads.
    """
    query = db.query(models.Message)

    if sender:
        query = query.filter(models.Message.sender.in_(get_phone_variants(sender)))
    if recipient:
        query = query.filter(models.Message.recipient.in_(get_phone_variants(recipient)))
    if from_datetime:
        query = query.filter(models.Message.timestamp >= from_datetime)
    if to_datetime:
        query = query.filter(models.Message.timestamp <= to_datetime)

    # Order newest first, but limit to prevent UI crashes
    query = query.order_by(models.Message.timestamp.desc()).limit(limit)
    
    return query.all()

@router.post("/mark-read/")
async def mark_thread_as_read(payload: MarkReadPayload, db: Session = Depends(get_db)):
    """
    Marks all inbound messages from a specific sender as viewed in the web UI.
    """
    normalized_phone = payload.phone.strip()
    phone_variants = get_phone_variants(normalized_phone)
    
    db.query(models.Message).filter(
        models.Message.sender.in_(phone_variants),
        models.Message.web_viewed == False
    ).update({"web_viewed": True}, synchronize_session=False)
    
    db.commit()
    await broadcaster.publish("thread_read", {"phone": normalized_phone})
    return {"status": "success"}