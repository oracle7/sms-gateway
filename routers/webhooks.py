import base64
import json
import logging
from datetime import timedelta
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, joinedload

from config import settings
from database import get_db, utc_now
from models import Contact, Message, MessageAttachment, MmsPending, RawWebhook
from routers.threads import serialize_message
from services.auth import verify_webhook_access
from services.broadcaster import broadcaster
from services.media import save_base64_attachment
from services.phone import normalize_contact_phone
from services.security import sanitize_webhook_payload
from services.threads import get_or_create_thread, recompute_thread_summary, thread_to_schema

logger = logging.getLogger("uvicorn.error")
router = APIRouter()


def _dump_raw_webhook(
    db: Session,
    *,
    endpoint: str,
    event_type: Optional[str],
    signature_valid: Optional[bool],
    processing_status: str,
    payload: dict,
) -> None:
    try:
        sanitized = sanitize_webhook_payload(payload)
        raw = RawWebhook(
            received_at=utc_now(),
            endpoint=endpoint,
            event_type=event_type,
            signature_valid=signature_valid,
            processing_status=processing_status,
            payload_sanitized=json.dumps(sanitized, ensure_ascii=True),
        )
        db.add(raw)
        db.commit()
    except Exception as exc:
        logger.error(f"Failed to dump sanitized raw webhook: {exc}")
        db.rollback()


def _extract_body(msg_data: dict) -> str:
    body = msg_data.get("text", msg_data.get("body", msg_data.get("message", "")))
    if isinstance(body, dict):
        body = body.get("text", "")
    return str(body) if body is not None else ""


@router.post("/inbound")
async def handle_inbound(
    request: Request,
    verified: Tuple[bytes, bool] = Depends(verify_webhook_access),
    db: Session = Depends(get_db),
):
    raw_body, sig_valid = verified
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload.")

    msg_data = payload.get("payload", payload.get("message", payload.get("data", payload)))
    if not isinstance(msg_data, dict):
        msg_data = {}
    action = str(payload.get("action", payload.get("event", msg_data.get("type", "")))).strip()

    raw_sender = msg_data.get(
        "address", msg_data.get("sender", msg_data.get("phoneNumber", msg_data.get("from", "")))
    )
    sender = normalize_contact_phone(raw_sender)
    raw_recipient = msg_data.get("recipient", msg_data.get("to", "")) or settings.SMS_DID
    recipient = normalize_contact_phone(raw_recipient)

    raw_msg_id = msg_data.get("messageId", msg_data.get("id"))
    gateway_msg_id = str(raw_msg_id).strip() if raw_msg_id else None
    transaction_id = msg_data.get("transactionId")
    transaction_id = str(transaction_id).strip() if transaction_id else None

    # Step 1: mms:received notification header (save to mms_pending, do not create empty chat bubble)
    if action == "mms:received":
        pending = MmsPending(
            gateway_message_id=gateway_msg_id,
            transaction_id=transaction_id,
            contact_phone=sender,
            recipient=recipient,
            subject=msg_data.get("subject"),
            received_at=utc_now(),
        )
        db.add(pending)
        db.commit()
        _dump_raw_webhook(
            db,
            endpoint="/webhook/inbound",
            event_type=action,
            signature_valid=sig_valid,
            processing_status="mms_pending_saved",
            payload=payload,
        )
        return {"status": "processed", "reason": "MMS pending metadata saved"}

    # Step 2: sms:received, sms:data-received, or mms:downloaded
    body = _extract_body(msg_data)
    now = utc_now()

    # Correlate mms:downloaded with mms_pending when Pixel 6 sends sender="unknown"
    matched_pending: Optional[MmsPending] = None
    if action == "mms:downloaded":
        cutoff = now - timedelta(minutes=15)
        base_q = db.query(MmsPending).filter(
            MmsPending.consumed_at.is_(None),
            MmsPending.received_at >= cutoff,
        )
        if gateway_msg_id:
            matched_pending = base_q.filter(MmsPending.gateway_message_id == gateway_msg_id).first()
        if not matched_pending and transaction_id:
            matched_pending = base_q.filter(MmsPending.transaction_id == transaction_id).first()
        if not matched_pending and sender != "unknown":
            matched_pending = (
                base_q.filter(MmsPending.contact_phone == sender)
                .order_by(MmsPending.received_at.desc())
                .first()
            )
        if not matched_pending and sender == "unknown":
            matched_pending = (
                base_q.filter(MmsPending.contact_phone != "unknown")
                .order_by(MmsPending.received_at.desc())
                .first()
            )
        if matched_pending:
            if sender == "unknown" and matched_pending.contact_phone != "unknown":
                sender = matched_pending.contact_phone
            matched_pending.consumed_at = now

    # Fallback if sender is still unknown: match most recent inbound sender to this recipient
    if sender == "unknown":
        recent_msg = (
            db.query(Message)
            .filter(
                Message.direction == "inbound",
                Message.contact_phone != "unknown",
                Message.recipient == recipient,
            )
            .order_by(Message.timestamp.desc())
            .first()
        )
        if recent_msg:
            sender = recent_msg.contact_phone

    db_msg: Optional[Message] = None
    if gateway_msg_id:
        db_msg = db.query(Message).filter(Message.gateway_message_id == gateway_msg_id).first()

    thread = get_or_create_thread(db, sender)
    # Reopen archived conversation automatically when a new patient message arrives
    if thread.archived_at is not None:
        thread.archived_at = None
        thread.archived_by_user_id = None

    if db_msg:
        if body and not db_msg.body:
            db_msg.body = body
        if sender != "unknown" and db_msg.contact_phone == "unknown":
            db_msg.contact_phone = sender
            db_msg.sender = sender
    else:
        db_msg = Message(
            gateway_message_id=gateway_msg_id,
            contact_phone=sender,
            direction="inbound",
            sender=sender,
            recipient=recipient,
            body=body,
            timestamp=now,
            status="received",
            is_delivered=True,
            read_at=None,
        )
        db.add(db_msg)
        db.flush()

    attachments = msg_data.get("attachments") or []
    for att in attachments:
        if not isinstance(att, dict):
            continue
        content_type = str(att.get("contentType", "application/octet-stream")).strip()
        ct_lower = content_type.lower()
        b64_data = att.get("data") or att.get("base64") or ""

        if ct_lower.startswith("application/smil"):
            continue

        if ct_lower.startswith("text/plain") and b64_data:
            try:
                decoded_text = base64.b64decode(b64_data).decode("utf-8", errors="ignore").strip()
                if decoded_text and not db_msg.body:
                    db_msg.body = decoded_text
            except Exception as exc:
                logger.warning(f"Failed to decode text/plain MMS part: {exc}")
            continue

        if b64_data:
            try:
                saved = save_base64_attachment(
                    b64_data=b64_data,
                    content_type=content_type,
                    original_name=att.get("name"),
                )
                db.add(
                    MessageAttachment(
                        message_id=db_msg.id,
                        storage_key=saved.storage_key,
                        original_filename=att.get("name"),
                        content_type=saved.content_type,
                        size_bytes=saved.size_bytes,
                        sha256=saved.sha256,
                    )
                )
            except Exception as exc:
                logger.error(f"Failed to save MMS attachment: {exc}")

    db.flush()
    thread = recompute_thread_summary(db, db_msg.contact_phone)
    db.commit()

    _dump_raw_webhook(
        db,
        endpoint="/webhook/inbound",
        event_type=action or "inbound",
        signature_valid=sig_valid,
        processing_status="processed",
        payload=payload,
    )

    loaded = (
        db.query(Message)
        .options(joinedload(Message.attachments), joinedload(Message.sent_by))
        .filter(Message.id == db_msg.id)
        .first()
    )
    contact = (
        db.query(Contact)
        .filter(Contact.phone_number == db_msg.contact_phone, Contact.deleted_at.is_(None))
        .first()
    )

    await broadcaster.publish(
        "message_created",
        {
            "message": serialize_message(loaded).model_dump(mode="json"),
            "thread": thread_to_schema(thread, contact).model_dump(mode="json"),
        },
    )
    return {"status": "processed", "id": db_msg.id}


@router.post("/status")
async def handle_status(
    request: Request,
    verified: Tuple[bytes, bool] = Depends(verify_webhook_access),
    db: Session = Depends(get_db),
):
    raw_body, sig_valid = verified
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload.")

    msg_data = payload.get("payload", payload.get("message", payload.get("data", payload)))
    if not isinstance(msg_data, dict):
        msg_data = {}
    action = str(payload.get("action", payload.get("event", msg_data.get("type", "")))).strip()
    raw_msg_id = msg_data.get("messageId", msg_data.get("id"))
    gateway_msg_id = str(raw_msg_id).strip() if raw_msg_id else ""

    if not gateway_msg_id:
        _dump_raw_webhook(
            db,
            endpoint="/webhook/status",
            event_type=action,
            signature_valid=sig_valid,
            processing_status="ignored_no_message_id",
            payload=payload,
        )
        return {"status": "ignored", "reason": "No messageId provided"}

    db_msg = db.query(Message).filter(Message.gateway_message_id == gateway_msg_id).first()
    if not db_msg:
        _dump_raw_webhook(
            db,
            endpoint="/webhook/status",
            event_type=action,
            signature_valid=sig_valid,
            processing_status="ignored_unknown_message",
            payload=payload,
        )
        return {"status": "ignored", "reason": "Message not found"}

    status_name = None
    if action == "sms:sent":
        db_msg.is_sent = True
        if db_msg.status == "queued":
            db_msg.status = "sent"
        status_name = "sent"
    elif action == "sms:delivered":
        db_msg.is_sent = True
        db_msg.is_delivered = True
        db_msg.status = "delivered"
        status_name = "delivered"
    elif action == "sms:failed":
        db_msg.is_failed = True
        db_msg.status = "failed"
        db_msg.error_reason = str(msg_data.get("reason", "Unknown failure"))
        status_name = "failed"
    elif action == "sms:cancelled":
        db_msg.is_cancelled = True
        db_msg.status = "cancelled"
        status_name = "cancelled"
    else:
        _dump_raw_webhook(
            db,
            endpoint="/webhook/status",
            event_type=action,
            signature_valid=sig_valid,
            processing_status="ignored_unknown_action",
            payload=payload,
        )
        return {"status": "ignored", "reason": f"Unhandled status action: {action}"}

    db.commit()
    _dump_raw_webhook(
        db,
        endpoint="/webhook/status",
        event_type=action,
        signature_valid=sig_valid,
        processing_status="processed",
        payload=payload,
    )

    await broadcaster.publish(
        "message_status_updated",
        {
            "id": db_msg.id,
            "gateway_message_id": db_msg.gateway_message_id,
            "contact_phone": db_msg.contact_phone,
            "status": db_msg.status,
            "is_sent": db_msg.is_sent,
            "is_delivered": db_msg.is_delivered,
            "is_failed": db_msg.is_failed,
            "is_cancelled": db_msg.is_cancelled,
            "error_reason": db_msg.error_reason,
            "event": status_name,
        },
    )
    return {"status": "success", "event": action}
