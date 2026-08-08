from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from database import get_db
import models, schemas

router = APIRouter()

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
        query = query.filter(models.Message.sender == sender)
    if recipient:
        query = query.filter(models.Message.recipient == recipient)
    if from_datetime:
        query = query.filter(models.Message.timestamp >= from_datetime)
    if to_datetime:
        query = query.filter(models.Message.timestamp <= to_datetime)

    # Order newest first, but limit to prevent UI crashes
    query = query.order_by(models.Message.timestamp.desc()).limit(limit)
    
    return query.all()