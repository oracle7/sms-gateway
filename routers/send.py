from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import httpx
import logging
import re
from datetime import datetime, timezone

from database import get_db
import models, schemas
from config import settings

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

def format_to_e164(phone: str) -> str:
    """Standardizes phone numbers for the UI."""
    clean = re.sub(r"\D", "", phone)
    if len(clean) == 10:
        return f"+1{clean}"
    elif len(clean) == 11 and clean.startswith("1"):
        return f"+{clean}"
    return f"+{clean}" if not phone.startswith("+") else phone

@router.post("/", response_model=schemas.MessageResponse)
async def send_message(payload: schemas.MessageSend, db: Session = Depends(get_db)):
    normalized_recipient = format_to_e164(payload.recipient)
    gateway_id = None
    
    # Format payload exactly how the Android app expects it
    gateway_payload = {
        "phoneNumbers": [normalized_recipient],
        "message": payload.body or ""
    }

    async with httpx.AsyncClient() as client:
        try:
            auth = httpx.BasicAuth(settings.SMS_API_LOGIN, settings.SMS_API_PASS)
            response = await client.post(
                f"{settings.SMS_API_URL.rstrip('/')}/messages",
                auth=auth,
                json=gateway_payload,
                timeout=15.0
            )
            
            if response.status_code not in (200, 201, 202, 204):
                logger.error(f"Gateway Rejection: {response.status_code} - {response.text}")
                raise HTTPException(status_code=400, detail="Android app rejected the request")
            
            # Extract the Android app's native ID so we can match it against the webhooks later
            try:
                res_data = response.json()
                gateway_id = str(res_data.get("id", ""))
            except Exception:
                pass
                
        except httpx.RequestError as e:
            logger.error(f"Failed to reach Android app: {e}")
            raise HTTPException(status_code=502, detail="Network error reaching phone")

    # Create the database record. 
    # Because this is outgoing, sender is NULL, and recipient is populated.
    db_msg = models.Message(
        message_id=gateway_id if gateway_id else None,
        sender=None, 
        recipient=normalized_recipient,
        body=payload.body or "",
        timestamp=datetime.now(timezone.utc),
        is_sent=False,
        is_delivered=False,
        is_read=False,
        is_failed=False,
        is_cancelled=False,
        # web_viewed is True because the user literally just typed and viewed it
        web_viewed=True 
    )
    
    db.add(db_msg)
    db.commit()
    db.refresh(db_msg)
    
    return db_msg