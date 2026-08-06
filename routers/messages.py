import asyncio
import logging
import re
import os
import aiofiles
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
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

MEDIA_DIR = "static/media"
os.makedirs(MEDIA_DIR, exist_ok=True)

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

    gateway_payload = {
        "phoneNumbers": [normalized_recipient],
        "message": payload.body or ""
    }

    if hasattr(payload, 'media_urls') and payload.media_urls:
        gateway_payload["attachments"] = payload.media_urls

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                PHONE_API_MESSAGES,
                auth=get_auth_headers(),
                json=gateway_payload,
                timeout=15.0
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

    db_msg = models.Message(
        raw_number=payload.recipient,
        body=payload.body or "",
        is_inbound=False,
        status="sent",
        gateway_id=gateway_id,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(db_msg)
    db.flush()

    if hasattr(payload, 'media_urls') and payload.media_urls:
        for url in payload.media_urls:
            db_attachment = models.MessageAttachment(
                message_id=db_msg.id,
                media_url=url
            )
            db.add(db_attachment)

    db.commit()
    db.refresh(db_msg)
    
    return {"status": "success", "message": db_msg}

@router.post("/webhook/inbound")
async def handle_inbound_sms(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    
    msg_id = payload.get("id")
    sender = payload.get("phoneNumber")
    body = payload.get("message", "")
    attachments = payload.get("attachments", [])

    db_msg = models.Message(
        raw_number=sender,
        body=body,
        is_inbound=True,
        status="received",
        gateway_id=msg_id,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(db_msg)
    db.flush()

    if attachments and msg_id:
        async with httpx.AsyncClient() as client:
            for att in attachments:
                part_id = att.get("partId")
                if not part_id:
                    continue
                
                download_url = f"{PHONE_API_INBOX}/{msg_id}/attachments/{part_id}"
                
                try:
                    response = await client.get(
                        download_url, 
                        auth=get_auth_headers(),
                        timeout=15.0
                    )
                    
                    if response.status_code == 200:
                        content_type = response.headers.get("Content-Type", "application/octet-stream")
                        ext = content_type.split("/")[-1] if "/" in content_type else "bin"
                        filename = f"{msg_id}_part{part_id}.{ext}"
                        filepath = os.path.join(MEDIA_DIR, filename)
                        
                        async with aiofiles.open(filepath, 'wb') as f:
                            await f.write(response.content)
                            
                        db_attachment = models.MessageAttachment(
                            message_id=db_msg.id,
                            media_url=f"/static/media/{filename}",
                            content_type=content_type
                        )
                        db.add(db_attachment)
                except httpx.RequestError as e:
                    logger.error(f"Falha ao baixar anexo {part_id} da msg {msg_id}: {str(e)}")

    db.commit()
    return {"status": "processed"}