from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
import logging
import json
import os
import base64
import uuid
from datetime import datetime, timezone

from database import get_db
import models
from config import settings
from services.broadcaster import broadcaster

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

MEDIA_DIR = "static/media"
os.makedirs(MEDIA_DIR, exist_ok=True)
DEBUG_LOG_FILE = "webhook_debug.jsonl"

async def dump_raw_webhook(payload: dict, db: Session):
    """Failsafe: Dumps raw incoming webhooks to the database."""
    try:
        raw = models.RawWebhookDump(payload=json.dumps(payload))
        db.add(raw)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to dump raw webhook: {e}")
        db.rollback()

@router.post("/inbound")
async def handle_inbound(request: Request, db: Session = Depends(get_db)):
    """
    Catches new incoming messages (sms:received, mms:received, mms:downloaded).
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Appending raw webhook to JSONL file for troubleshooting
    try:
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception as e:
        logger.error(f"Failed to write to debug file: {e}")

    await dump_raw_webhook(payload, db)

    msg_data = payload.get("payload", payload.get("message", payload.get("data", payload)))
    action = payload.get("action", payload.get("event", msg_data.get("type", "")))

    sender = msg_data.get("address", msg_data.get("sender", msg_data.get("from", "")))
    recipient = msg_data.get("recipient", msg_data.get("to", "")) or settings.SMS_DID
    message_id = msg_data.get("messageId", msg_data.get("id", None))
    if message_id:
        message_id = str(message_id)

    # ---------------------------------------------------------
    # STEP 1: Process mms:received (Save sender & message_id metadata)
    # ---------------------------------------------------------
    if action == "mms:received":
        if message_id and sender and sender != "unknown":
            existing = db.query(models.Message).filter(models.Message.message_id == message_id).first()
            if not existing:
                pending_msg = models.Message(
                    message_id=message_id,
                    sender=sender,
                    recipient=recipient,
                    body="",
                    timestamp=datetime.now(timezone.utc),
                    is_delivered=True
                )
                db.add(pending_msg)
                db.commit()
                logger.info(f"Registered MMS header for message_id {message_id} from {sender}")
        return {"status": "processed", "reason": "MMS header metadata saved"}

    # ---------------------------------------------------------
    # STEP 2: Process sms:received or mms:downloaded
    # ---------------------------------------------------------
    body = msg_data.get("text", msg_data.get("body", msg_data.get("message", "")))
    if isinstance(body, dict):
        body = body.get("text", "")

    db_msg = None
    if message_id:
        db_msg = db.query(models.Message).filter(models.Message.message_id == message_id).first()

    if db_msg:
        # Update the existing record created during mms:received
        if body:
            db_msg.body = body
        if sender and sender != "unknown":
            db_msg.sender = sender
    else:
        # Fallback: Check if sender is unknown and resolve from last valid interaction
        if (not sender or sender == "unknown"):
            last_valid_msg = db.query(models.Message).filter(
                models.Message.sender != "unknown",
                models.Message.sender != None,
                models.Message.sender != settings.SMS_DID,
                models.Message.recipient == recipient
            ).order_by(models.Message.timestamp.desc()).first()

            if last_valid_msg:
                sender = last_valid_msg.sender

        if not sender and not recipient:
            logger.warning("Ghost message rejected: Both sender and recipient are empty.")
            return {"status": "ignored", "reason": "Missing sender and recipient"}

        db_msg = models.Message(
            message_id=message_id,
            sender=sender,
            recipient=recipient,
            body=body or "",
            timestamp=datetime.now(timezone.utc),
            is_delivered=True
        )
        db.add(db_msg)

    db.flush() # Generate db_msg.id for attachments

    # Process Attachments (specifically for mms:downloaded)
    attachments = msg_data.get("attachments", [])
    processed_attachments = []

    if attachments:
        clean_number = "".join(filter(str.isdigit, db_msg.sender)) or "unknown"
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        for index, att in enumerate(attachments):
            content_type = att.get("contentType", "application/octet-stream")
            b64_data = att.get("data", att.get("base64", ""))

            if b64_data:
                ext = content_type.split("/")[-1] if "/" in content_type else "bin"
                if ext == "jpeg":
                    ext = "jpg"

                filename = f"{clean_number}_{timestamp_str}_{index}.{ext}"
                filepath = os.path.join(MEDIA_DIR, filename)

                try:
                    with open(filepath, "wb") as f:
                        f.write(base64.b64decode(b64_data))

                    db_attachment = models.MessageAttachment(
                        message_id=db_msg.id,
                        filename=f"/static/media/{filename}",
                        content_type=content_type
                    )
                    db.add(db_attachment)
                    processed_attachments.append({
                        "filename": db_attachment.filename,
                        "content_type": content_type
                    })
                except Exception as e:
                    logger.error(f"Failed to save attachment {filename}: {e}")

    db.commit()
    db.refresh(db_msg)

    # ---------------------------------------------------------
    # Broadcast to web UI via SSE
    # ---------------------------------------------------------
    broadcast_data = {
        "id": db_msg.id,
        "message_id": db_msg.message_id,
        "sender": db_msg.sender,
        "recipient": db_msg.recipient,
        "body": db_msg.body,
        "is_inbound": True,
        "attachments": processed_attachments
    }
    await broadcaster.publish("new_message", broadcast_data)

    return {"status": "processed"}

@router.post("/status")
async def handle_status(request: Request, db: Session = Depends(get_db)):
    """
    Catches lifecycle events for outbound messages:
    sms:sent, sms:delivered, sms:failed, sms:cancelled.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception as e:
        logger.error(f"Failed to write to debug file: {e}")

    await dump_raw_webhook(payload, db)

    msg_data = payload.get("payload", payload.get("message", payload.get("data", payload)))
    action = payload.get("action", payload.get("event", msg_data.get("type", "")))
    message_id = str(msg_data.get("messageId", msg_data.get("id", "")))

    if not message_id:
        return {"status": "ignored", "reason": "No messageId provided"}

    db_msg = db.query(models.Message).filter(models.Message.message_id == message_id).first()

    if not db_msg:
        logger.warning(f"Status update received for unknown message_id: {message_id}")
        return {"status": "ignored", "reason": "Message not found in DB"}

    status_updated = False

    if action == "sms:sent":
        db_msg.is_sent = True
        status_updated = "sent"
    elif action == "sms:delivered":
        db_msg.is_delivered = True
        status_updated = "delivered"
    elif action == "sms:failed":
        db_msg.is_failed = True
        db_msg.error_reason = msg_data.get("reason", "Unknown failure")
        status_updated = "failed"
    elif action == "sms:cancelled":
        db_msg.is_cancelled = True
        status_updated = "cancelled"
    else:
        return {"status": "ignored", "reason": f"Unknown status action: {action}"}

    db.commit()

    if status_updated:
        await broadcaster.publish("status_update", {
            "internal_id": db_msg.id,
            "message_id": db_msg.message_id,
            "status": status_updated,
            "error_reason": db_msg.error_reason
        })

    return {"status": "success", "event": action}