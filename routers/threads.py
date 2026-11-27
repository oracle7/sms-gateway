from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from database import get_db, utc_now
from models import Contact, Message, Thread
from schemas import (
    AttachmentResponse,
    MessagePageResponse,
    MessageResponse,
    ThreadListResponse,
)
from services.audit import record_audit
from services.auth import AuthContext, extract_client_ip, require_auth, require_csrf
from services.broadcaster import broadcaster
from services.phone import normalize_contact_phone
from services.threads import (
    get_or_create_thread,
    list_threads,
    recompute_thread_summary,
    thread_to_schema,
)

router = APIRouter()


def serialize_message(msg: Message) -> MessageResponse:
    return MessageResponse(
        id=msg.id,
        gateway_message_id=msg.gateway_message_id,
        contact_phone=msg.contact_phone,
        direction=msg.direction,
        sender=msg.sender,
        recipient=msg.recipient,
        body=msg.body or "",
        timestamp=msg.timestamp,
        sent_by_user_id=msg.sent_by_user_id,
        sent_by_display_name=msg.sent_by.display_name if msg.sent_by else None,
        status=msg.status,
        is_sent=msg.is_sent,
        is_delivered=msg.is_delivered,
        is_failed=msg.is_failed,
        is_cancelled=msg.is_cancelled,
        error_reason=msg.error_reason,
        read_at=msg.read_at,
        deleted_at=msg.deleted_at,
        attachments=[
            AttachmentResponse(
                id=att.id,
                filename=att.original_filename or att.storage_key.split("/")[-1],
                original_filename=att.original_filename,
                content_type=att.content_type,
                size_bytes=att.size_bytes,
                url=f"/api/attachments/{att.id}",
            )
            for att in msg.attachments
        ],
    )


@router.get("", response_model=ThreadListResponse)
@router.get("/", response_model=ThreadListResponse)
def get_threads(
    status_filter: Literal["active", "archived"] = Query("active", alias="status"),
    q: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    items, total, total_unread_active = list_threads(
        db, status=status_filter, q=q, limit=limit, offset=offset
    )
    return ThreadListResponse(
        items=items,
        total=total,
        total_unread_active=total_unread_active,
        limit=limit,
        offset=offset,
        has_more=(offset + len(items)) < total,
    )


@router.get("/{phone}/messages", response_model=MessagePageResponse)
def get_thread_messages(
    phone: str,
    before_ts: Optional[datetime] = None,
    before_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    include_hidden: bool = False,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    if include_hidden and auth.user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can view hidden messages.",
        )

    canonical = normalize_contact_phone(phone)
    thread = db.query(Thread).filter(Thread.contact_phone == canonical).first()
    contact = (
        db.query(Contact)
        .filter(Contact.phone_number == canonical, Contact.deleted_at.is_(None))
        .first()
    )

    if not thread:
        thread = get_or_create_thread(db, canonical)
        db.commit()

    query = (
        db.query(Message)
        .options(joinedload(Message.attachments), joinedload(Message.sent_by))
        .filter(Message.contact_phone == canonical)
    )
    if not include_hidden:
        query = query.filter(Message.deleted_at.is_(None))

    if before_ts is not None:
        if before_id:
            query = query.filter(
                or_(
                    Message.timestamp < before_ts,
                    and_(Message.timestamp == before_ts, Message.id < before_id),
                )
            )
        else:
            query = query.filter(Message.timestamp < before_ts)

    rows = (
        query.order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(limit + 1)
        .all()
    )
    has_more = len(rows) > limit
    page_rows = list(reversed(rows[:limit]))

    next_before_ts = page_rows[0].timestamp if (has_more and page_rows) else None
    next_before_id = page_rows[0].id if (has_more and page_rows) else None

    return MessagePageResponse(
        thread=thread_to_schema(thread, contact),
        items=[serialize_message(m) for m in page_rows],
        has_more=has_more,
        next_before_ts=next_before_ts,
        next_before_id=next_before_id,
    )


@router.post("/{phone}/mark-read")
async def mark_thread_read(
    phone: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    canonical = normalize_contact_phone(phone)
    now = utc_now()
    updated = (
        db.query(Message)
        .filter(
            Message.contact_phone == canonical,
            Message.direction == "inbound",
            Message.deleted_at.is_(None),
            Message.read_at.is_(None),
        )
        .update({"read_at": now, "read_by_user_id": auth.user.id}, synchronize_session=False)
    )
    thread = recompute_thread_summary(db, canonical)

    if updated > 0:
        record_audit(
            db,
            action="thread.marked_read",
            resource_type="thread",
            resource_id=canonical,
            actor_user=auth.user,
            ip_address=extract_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            metadata={"marked_count": updated},
            commit=False,
        )
    db.commit()

    if updated > 0:
        await broadcaster.publish(
            "thread_read",
            {"contact_phone": canonical, "unread_count": thread.unread_count},
        )
    return {"status": "success", "marked_count": updated, "unread_count": thread.unread_count}


@router.post("/{phone}/archive")
async def archive_thread(
    phone: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    canonical = normalize_contact_phone(phone)
    thread = get_or_create_thread(db, canonical)
    if thread.archived_at is None:
        thread.archived_at = utc_now()
        thread.archived_by_user_id = auth.user.id
        thread.updated_at = utc_now()
        record_audit(
            db,
            action="thread.archived",
            resource_type="thread",
            resource_id=canonical,
            actor_user=auth.user,
            ip_address=extract_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            commit=False,
        )
        db.commit()

    contact = (
        db.query(Contact)
        .filter(Contact.phone_number == canonical, Contact.deleted_at.is_(None))
        .first()
    )
    await broadcaster.publish(
        "thread_updated",
        thread_to_schema(thread, contact).model_dump(mode="json"),
    )
    return {"status": "archived", "contact_phone": canonical}


@router.post("/{phone}/unarchive")
async def unarchive_thread(
    phone: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    canonical = normalize_contact_phone(phone)
    thread = get_or_create_thread(db, canonical)
    if thread.archived_at is not None:
        thread.archived_at = None
        thread.archived_by_user_id = None
        thread.updated_at = utc_now()
        record_audit(
            db,
            action="thread.unarchived",
            resource_type="thread",
            resource_id=canonical,
            actor_user=auth.user,
            ip_address=extract_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            commit=False,
        )
        db.commit()

    contact = (
        db.query(Contact)
        .filter(Contact.phone_number == canonical, Contact.deleted_at.is_(None))
        .first()
    )
    await broadcaster.publish(
        "thread_updated",
        thread_to_schema(thread, contact).model_dump(mode="json"),
    )
    return {"status": "active", "contact_phone": canonical}
