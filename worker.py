from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
import logging
import json
import os
import re
import base64
from datetime import datetime, timezone
import uuid

# Import your database and models
# Adjust these imports if your file structure is slightly different!
from database import SessionLocal 
from models import Message, MessageAttachment, RawWebhookDump

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

MEDIA_DIR = "static/media"
os.makedirs(MEDIA_DIR, exist_ok=True)

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    # ---------------------------------------------------------
    # STEP 1: CATCH THE RAW PAYLOAD
    # ---------------------------------------------------------
    try:
        payload = await request.json()
    except Exception:
        logger.error("Webhook rejected: Invalid JSON received.")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # ---------------------------------------------------------
    # STEP 2: THE FAIL-SAFE DUMP
    # ---------------------------------------------------------
    try:
        raw_dump = RawWebhookDump(payload=json.dumps(payload))
        db.add(raw_dump)
        db.commit()
        logger.info(f"Failsafe triggered: Webhook payload safely stored. (ID: {raw_dump.id})")
    except Exception as e:
        logger.error(f"CRITICAL ERROR saving webhook failsafe: {e}")
        db.rollback()
        # Force a 500 error so the phone knows the delivery failed and retries later!
        raise HTTPException(status_code=500, detail="Failsafe storage error")

    # ---------------------------------------------------------
    # STEP 3: PROCESS AND EXTRACT METADATA
    # ---------------------------------------------------------
    try:
        # Some webhooks wrap the message in a "message" or "data" key, others send it flat.
        msg_data = payload.get("message", payload.get("data", payload))
        
        # --- NEW: IGNORE MMS HEADERS ---
        msg_type = msg_data.get("type")
        if msg_type == "MMS":
            logger.info("Ignoring MMS notification header payload.")
            return {"status": "ignored", "reason": "MMS notification header"}

        gateway_id_str = str(msg_data.get("id", ""))
        
        # Check for duplicates so we don't save the same retry twice
        if gateway_id_str:
            existing_msg = db.query(Message).filter(Message.gateway_id == gateway_id_str).first()
            if existing_msg:
                logger.info(f"Webhook received duplicate message (Gateway ID: {gateway_id_str}). Ignoring.")
                return {"status": "success", "message": "Already processed"}

        raw_number = msg_data.get("sender", msg_data.get("from", ""))
        is_inbound = True
        
        # --- NEW: GHOST SENDER PREVENTION ---
        if not raw_number or raw_number == "null" or str(raw_number).lower() == "unknown":
            # Check if it's an outgoing message the app is syncing
            recipient = msg_data.get("recipient", msg_data.get("to", ""))
            if recipient and recipient != "null" and str(recipient).lower() != "unknown":
                raw_number = recipient
                is_inbound = False
            else:
                logger.warning(f"Skipping payload {gateway_id_str} with unknown sender/recipient.")
                return {"status": "ignored", "reason": "Unknown sender"}

        body = msg_data.get("body", msg_data.get("contentPreview", msg_data.get("text", "")))
        
        # We generate our own internal UUID, but keep the gateway_id
        internal_id = str(uuid.uuid4())
        
        new_message = Message(
            id=internal_id,
            gateway_id=gateway_id_str if gateway_id_str else None,
            raw_number=raw_number,
            body=body,
            timestamp=datetime.now(timezone.utc),
            is_inbound=is_inbound,
            status="delivered"
        )
        db.add(new_message)

        # ---------------------------------------------------------
        # STEP 4: PROCESS MEDIA / ATTACHMENTS
        # ---------------------------------------------------------
        attachments = msg_data.get("attachments", [])
        
        if attachments:
            # Clean the phone number for the filename (keep only digits)
            clean_number = re.sub(r'\D', '', raw_number)
            if not clean_number:
                clean_number = "unknown"
                
            # Create the YYYYMMDD_HHMMSS string
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

            for index, att in enumerate(attachments):
                content_type = att.get("contentType", "application/octet-stream")
                
                # SMS Gateway usually sends base64 under 'data', 'content', or 'base64'
                b64_data = att.get("data", att.get("content", att.get("base64", "")))
                
                if b64_data:
                    # Determine extension
                    ext = content_type.split("/")[-1] if "/" in content_type else "bin"
                    if ext == "jpeg": 
                        ext = "jpg"
                        
                    # Create the perfect filename: [number]_[datetime]_[index].[ext]
                    filename = f"{clean_number}_{timestamp_str}_{index}.{ext}"
                    filepath = os.path.join(MEDIA_DIR, filename)
                    
                    # Decode and save the file
                    with open(filepath, "wb") as f:
                        f.write(base64.b64decode(b64_data))
                        
                    logger.info(f"Media saved successfully: {filepath}")
                    
                    # Link to database
                    db_attachment = MessageAttachment(
                        message_id=internal_id,
                        media_url=f"/static/media/{filename}",
                        content_type=content_type
                    )
                    db.add(db_attachment)

        # ---------------------------------------------------------
        # STEP 5: COMMIT AND ACKNOWLEDGE
        # ---------------------------------------------------------
        db.commit()
        logger.info(f"Webhook processing complete for message from {raw_number}.")
        return {"status": "success", "message": "Webhook processed safely"}

    except Exception as e:
        logger.error(f"Error processing webhook data: {e}")
        db.rollback()
        # The raw payload is ALREADY saved from Step 2, so data is safe.
        # We throw 500 so the app retries.
        raise HTTPException(status_code=500, detail="Processing error")