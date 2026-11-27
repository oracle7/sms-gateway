import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, joinedload

from config import settings
from database import get_db, utc_now
from models import Contact, Message
from routers.threads import serialize_message
from schemas import MessageResponse, MessageSendRequest
from services.audit import record_audit
from services.auth import (
    AuthContext,
    extract_client_ip,
    require_admin_csrf,
    require_csrf,
)
from services.broadcaster import broadcaster
from services.gateway_client import send_sms_to_gateway
from services.phone import normalize_contact_phone
from services.threads import get_or_create_thread, recompute_thread_summary, thread_to_schema

logger = logging.getLogger("uvicorn.error")
router = APIRouter()


@router.post("", response_model=MessageResponse)
@router.post("/", response_model=MessageResponse)
async def send_message(
    payload: MessageSendRequest,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message text cannot be empty.")

    contact_phone = normalize_contact_phone(payload.recipient)
    if contact_phone == "unknown":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Valid recipient phone number is required.")

    try:
        gateway_id = await send_sms_to_gateway(contact_phone, body)
    except httpx.RequestError as exc:
        logger.error(f"Network error reaching Pixel 6 gateway: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the Pixel 6 phone gateway. Your message was not sent.",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    now = utc_now()
    thread = get_or_create_thread(db, contact_phone)
    if thread.archived_at is not None:
        thread.archived_at = None
        thread.archived_by_user_id = None

    msg = Message(
        gateway_message_id=gateway_id,
        contact_phone=contact_phone,
        direction="outbound",
        sender=normalize_contact_phone(settings.SMS_DID),
        recipient=contact_phone,
        body=body,
        timestamp=now,
        sent_by_user_id=auth.user.id,
        status="queued",
        is_sent=False,
        is_delivered=False,
        is_failed=False,
        is_cancelled=False,
        read_at=now,
        read_by_user_id=auth.user.id,
    )
    db.add(msg)
    db.flush()

    thread = recompute_thread_summary(db, contact_phone)
    record_audit(
        db,
        action="message.sent",
        resource_type="message",
        resource_id=msg.id,
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"contact_phone": contact_phone},
        commit=False,
    )
    db.commit()

    loaded = (
        db.query(Message)
        .options(joinedload(Message.attachments), joinedload(Message.sent_by))
        .filter(Message.id == msg.id)
        .first()
    )
    serialized = serialize_message(loaded)
    contact = (
        db.query(Contact)
        .filter(Contact.phone_number == contact_phone, Contact.deleted_at.is_(None))
        .first()
    )

    await broadcaster.publish(
        "message_created",
        {
            "message": serialized.model_dump(mode="json"),
            "thread": thread_to_schema(thread, contact).model_dump(mode="json"),
        },
    )
    return serialized


@router.post("/{message_id}/hide")
async def hide_message(
    message_id: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found.")

    if msg.deleted_at is None:
        msg.deleted_at = utc_now()
        msg.deleted_by_user_id = auth.user.id
        thread = recompute_thread_summary(db, msg.contact_phone)
        record_audit(
            db,
            action="message.hidden",
            resource_type="message",
            resource_id=msg.id,
            actor_user=auth.user,
            ip_address=extract_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            metadata={"contact_phone": msg.contact_phone},
            commit=False,
        )
        db.commit()

        contact = (
            db.query(Contact)
            .filter(Contact.phone_number == msg.contact_phone, Contact.deleted_at.is_(None))
            .first()
        )
        await broadcaster.publish(
            "message_hidden",
            {
                "message_id": msg.id,
                "contact_phone": msg.contact_phone,
                "thread": thread_to_schema(thread, contact).model_dump(mode="json"),
            },
        )
    return {"status": "hidden", "message_id": msg.id}


@router.post("/{message_id}/restore")
async def restore_message(
    message_id: str,
    request: Request,
    auth: AuthContext = Depends(require_admin_csrf),
    db: Session = Depends(get_db),
):
    msg = (
        db.query(Message)
        .options(joinedload(Message.attachments), joinedload(Message.sent_by))
        .filter(Message.id == message_id)
        .first()
    )
    if not msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found.")

    if msg.deleted_at is not None:
        msg.deleted_at = None
        msg.deleted_by_user_id = None
        thread = recompute_thread_summary(db, msg.contact_phone)
        record_audit(
            db,
            action="message.restored",
            resource_type="message",
            resource_id=msg.id,
            actor_user=auth.user,
            ip_address=extract_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            metadata={"contact_phone": msg.contact_phone},
            commit=False,
        )
        db.commit()
        db.refresh(msg)

        contact = (
            db.query(Contact)
            .filter(Contact.phone_number == msg.contact_phone, Contact.deleted_at.is_(None))
            .first()
        )
        await broadcaster.publish(
            "message_restored",
            {
                "message": serialize_message(msg).model_dump(mode="json"),
                "thread": thread_to_schema(thread, contact).model_dump(mode="json"),
            },
        )
    return {"status": "restored", "message_id": msg.id}
