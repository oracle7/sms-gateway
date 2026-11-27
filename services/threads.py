from typing import List, Literal, Optional, Tuple
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import utc_now
from models import Contact, Message, MessageAttachment, Thread
from schemas import ThreadResponse
from services.phone import format_phone_display, normalize_contact_phone


def get_or_create_thread(db: Session, contact_phone: str) -> Thread:
    canonical = normalize_contact_phone(contact_phone)
    thread = db.query(Thread).filter(Thread.contact_phone == canonical).first()
    if not thread:
        now = utc_now()
        thread = Thread(
            contact_phone=canonical,
            unread_count=0,
            created_at=now,
            updated_at=now,
        )
        db.add(thread)
        db.flush()
    return thread


def recompute_thread_summary(db: Session, contact_phone: str) -> Thread:
    """
    Recomputes a thread's latest non-deleted message preview, direction, timestamp,
    and shared unread_count from the messages table.
    """
    thread = get_or_create_thread(db, contact_phone)
    canonical = thread.contact_phone

    latest = (
        db.query(Message)
        .filter(
            Message.contact_phone == canonical,
            Message.deleted_at.is_(None),
        )
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .first()
    )

    unread = (
        db.query(func.count(Message.id))
        .filter(
            Message.contact_phone == canonical,
            Message.direction == "inbound",
            Message.deleted_at.is_(None),
            Message.read_at.is_(None),
        )
        .scalar()
        or 0
    )

    if latest:
        preview = (latest.body or "").strip()
        if not preview:
            has_att = (
                db.query(MessageAttachment.id)
                .filter(MessageAttachment.message_id == latest.id)
                .first()
                is not None
            )
            preview = "[Media attachment]" if has_att else "[MMS message]"
        if len(preview) > 160:
            preview = preview[:157] + "..."

        thread.last_message_id = latest.id
        thread.last_message_at = latest.timestamp
        thread.last_message_preview = preview
        thread.last_message_direction = latest.direction
    else:
        thread.last_message_id = None
        thread.last_message_at = None
        thread.last_message_preview = ""
        thread.last_message_direction = None

    thread.unread_count = int(unread)
    thread.updated_at = utc_now()
    db.flush()
    return thread


def thread_to_schema(thread: Thread, contact: Optional[Contact]) -> ThreadResponse:
    active_contact = contact if (contact and contact.deleted_at is None) else None
    return ThreadResponse(
        contact_phone=thread.contact_phone,
        display_phone=format_phone_display(thread.contact_phone),
        contact_name=active_contact.name if active_contact else None,
        contact_notes=active_contact.notes if active_contact else None,
        last_message_id=thread.last_message_id,
        last_message_at=thread.last_message_at,
        last_message_preview=thread.last_message_preview or "",
        last_message_direction=thread.last_message_direction,
        unread_count=thread.unread_count or 0,
        archived_at=thread.archived_at,
    )


def list_threads(
    db: Session,
    *,
    status: Literal["active", "archived"] = "active",
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[ThreadResponse], int, int]:
    """
    Returns paginated threads with active contact metadata and total active unread count.
    """
    query = db.query(Thread, Contact).outerjoin(
        Contact,
        (Contact.phone_number == Thread.contact_phone) & (Contact.deleted_at.is_(None)),
    )

    if status == "archived":
        query = query.filter(Thread.archived_at.is_not(None))
    else:
        query = query.filter(Thread.archived_at.is_(None))

    if q and q.strip():
        term = q.strip()
        like_term = f"%{term}%"
        digits_only = "".join(ch for ch in term if ch.isdigit())
        matching_msg_phones = (
            db.query(Message.contact_phone)
            .filter(Message.deleted_at.is_(None), Message.body.ilike(like_term))
            .distinct()
        )
        filters = [
            Thread.contact_phone.ilike(like_term),
            Contact.name.ilike(like_term),
            Thread.contact_phone.in_(matching_msg_phones),
        ]
        if digits_only:
            filters.append(Thread.contact_phone.ilike(f"%{digits_only}%"))
        query = query.filter(or_(*filters))

    total = query.count()
    rows = (
        query.order_by(Thread.last_message_at.desc().nullslast(), Thread.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    total_unread_active = (
        db.query(func.coalesce(func.sum(Thread.unread_count), 0))
        .filter(Thread.archived_at.is_(None))
        .scalar()
        or 0
    )

    items = [thread_to_schema(t, c) for t, c in rows]
    return items, int(total), int(total_unread_active)
