import asyncio
import logging
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import httpx
from database import get_db, SessionLocal
from config import settings
import models, schemas

logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/messages", tags=["Messages"])

PHONE_API_BASE = settings.SMS_API_URL.rstrip('/')
PHONE_API_MESSAGES = f"{PHONE_API_BASE}/messages"  # Used for POST
PHONE_API_INBOX = f"{PHONE_API_BASE}/inbox"        # Used for GET

def get_auth_headers():
    return httpx.BasicAuth(settings.SMS_API_LOGIN, settings.SMS_API_PASS)

def format_to_e164(phone: str) -> str:
    clean = re.sub(r"\D", "", phone)
    if len(clean) == 10:
        return f"+1{clean}"
    elif len(clean) == 11 and clean.startswith("1"):
        return f"+{clean}"
    return f"+{clean}" if not phone.startswith("+") else phone

@router.get("/", response_model=List[schemas.MessageResponse])
def get_messages(limit: int = 500, db: Session = Depends(get_db)):
    return db.query(models.Message).order_by(models.Message.timestamp.desc()).limit(limit).all()

@router.get("/search", response_model=List[schemas.MessageResponse])
def search_messages(query: str, db: Session = Depends(get_db)):
    if not query:
        return []
    search_term = f"%{query}%"
    return db.query(models.Message).filter(models.Message.body.ilike(search_term)).order_by(models.Message.timestamp.desc()).all()

@router.post("/send")
async def send_message(payload: schemas.MessageSend, db: Session = Depends(get_db)):
    normalized_recipient = format_to_e164(payload.recipient)
    gateway_id = None

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                PHONE_API_MESSAGES,
                auth=get_auth_headers(),
                json={
                    "phoneNumbers": [normalized_recipient],
                    "message": payload.body
                },
                timeout=10.0
            )
            
            if response.status_code not in (200, 201, 202, 204):
                logger.error("--- GATEWAY REJECTION DETECTED ---")
                logger.error(f"HTTP Status: {response.status_code}")
                logger.error(f"Raw Response Body: {response.text}")
                raise HTTPException(status_code=400, detail="Gateway Rejected Outbound Request.")
            
            try:
                res_data = response.json()
                gateway_id = res_data.get("id")
            except Exception:
                pass
                
        except httpx.RequestError as e:
            logger.error(f"Network transport failure reaching Android transceiver: {str(e)}")
            raise HTTPException(status_code=502, detail=f"Failed to communicate with phone: {str(e)}")

    # Fix: Added timestamp using current UTC time
    db_msg = models.Message(
        raw_number=payload.recipient,
        body=payload.body,
        is_inbound=False,
        status="sent",
        gateway_id=gateway_id,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(db_msg)
    db.commit()
    db.refresh(db_msg)
    
    return {"status": "success", "message": db_msg}