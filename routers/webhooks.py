from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
import logging
import json
import os
import base64
import uuid
import re
from datetime import datetime, timezone, timedelta

from database import get_db
import models
from config import settings
from services.broadcaster import broadcaster

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

MEDIA_DIR = "static/media"
os.makedirs(MEDIA_DIR, exist_ok=True)


def format_to_e164(phone: str) -> str:
    """Standardizes phone numbers to E.164 format."""
    if not phone:
        return ""
    phone = str(phone).strip()
    clean = re.sub(r"\D", "", phone)
    if not clean:
        return phone
    if len(clean) == 10:
        return f"+1{clean}"
    elif len(clean) == 11 and clean.startswith("1"):
        return f"+{clean}"
    return f"+{clean}"

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

    await dump_raw_webhook(payload, db)

    msg_data = payload.get("payload", payload.get("message", payload.get("data", payload)))
    action = payload.get("action", payload.get("event", msg_data.get("type", "")))

    raw_sender = msg_data.get("address", msg_data.get("sender", msg_data.get("phoneNumber", msg_data.get("from", ""))))
    if raw_sender and str(raw_sender).strip().lower() != "unknown":
        sender = format_to_e164(raw_sender)
    else:
        sender = raw_sender
    raw_recipient = msg_data.get("recipient", msg_data.get("to", "")) or settings.SMS_DID
    recipient = format_to_e164(raw_recipient)
    normalized_did = format_to_e164(settings.SMS_DID)
    message_id = msg_data.get("messageId", msg_data.get("id", None))
    if message_id:
        message_id = str(message_id)

    # ---------------------------------------------------------
    # STEP 1: Process mms:received (Save sender & message_id metadata)
    # ---------------------------------------------------------
    if action == "mms:received":
        if message_id and sender and str(sender).strip().lower() != "unknown":
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
        if sender and str(sender).strip().lower() != "unknown":
            db_msg.sender = sender
        db_msg.timestamp = datetime.now(timezone.utc)
        db_msg.web_viewed = False
    else:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).replace(tzinfo=None)

        if action == "mms:downloaded":
            if sender and str(sender).strip().lower() != "unknown":
                pending_mms = db.query(models.Message).filter(
                    models.Message.sender == sender,
                    models.Message.body == "",
                    models.Message.timestamp >= cutoff,
                    ~models.Message.attachments.any()
                ).order_by(models.Message.timestamp.desc()).first()

                if pending_mms:
                    db_msg = pending_mms
                    if message_id:
                        db_msg.message_id = message_id
                    if body:
                        db_msg.body = body
                    db_msg.timestamp = datetime.now(timezone.utc)
                    db_msg.web_viewed = False
            else:
                pending_mms = db.query(models.Message).filter(
                    models.Message.body == "",
                    models.Message.sender != None,
                    models.Message.sender != "unknown",
                    models.Message.sender != normalized_did,
                    models.Message.timestamp >= cutoff,
                    ~models.Message.attachments.any()
                ).order_by(models.Message.timestamp.desc()).first()

                if pending_mms:
                    db_msg = pending_mms
                    sender = format_to_e164(pending_mms.sender)
                    db_msg.sender = sender
                    if message_id:
                        db_msg.message_id = message_id
                    if body:
                        db_msg.body = body
                    db_msg.timestamp = datetime.now(timezone.utc)
                    db_msg.web_viewed = False

        if not db_msg:
            # Fallback: Check if sender is unknown and resolve from last valid interaction
            if not sender or str(sender).strip().lower() == "unknown":
                last_valid_msg = db.query(models.Message).filter(
                    models.Message.sender != "unknown",
                    models.Message.sender != None,
                    models.Message.sender != normalized_did,
                    models.Message.recipient == recipient
                ).order_by(models.Message.timestamp.desc()).first()

                if last_valid_msg:
                    sender = format_to_e164(last_valid_msg.sender)

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
        clean_number = "".join(filter(str.isdigit, db_msg.sender or "")) or "unknown"
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        for index, att in enumerate(attachments):
            content_type = att.get("contentType", "application/octet-stream")
            b64_data = att.get("data", att.get("base64", ""))

            if b64_data:
                if content_type.lower().startswith("text/plain"):
                    try:
                        decoded_text = base64.b64decode(b64_data).decode("utf-8", errors="ignore").strip()
                        if decoded_text and not db_msg.body:
                            db_msg.body = decoded_text
                    except Exception as e:
                        logger.error(f"Failed to decode text/plain MMS attachment: {e}")
                    continue

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
        "timestamp": db_msg.timestamp.isoformat() if db_msg.timestamp else None,
        "is_inbound": True,
        "is_sent": db_msg.is_sent if hasattr(db_msg, 'is_sent') else False,
        "is_delivered": db_msg.is_delivered if hasattr(db_msg, 'is_delivered') else False,
        "is_read": db_msg.is_read if hasattr(db_msg, 'is_read') else False,
        "is_failed": db_msg.is_failed if hasattr(db_msg, 'is_failed') else False,
        "is_cancelled": db_msg.is_cancelled if hasattr(db_msg, 'is_cancelled') else False,
        "error_reason": db_msg.error_reason if hasattr(db_msg, 'error_reason') else None,
        "web_viewed": db_msg.web_viewed if hasattr(db_msg, 'web_viewed') else False,
        "attachments": [
            {"filename": a.filename, "content_type": a.content_type}
            for a in db_msg.attachments
        ]
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
