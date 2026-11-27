from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db, utc_now
from models import Contact
from schemas import ContactCreate, ContactResponse, ContactUpdate
from services.audit import record_audit
from services.auth import AuthContext, extract_client_ip, require_auth, require_csrf
from services.broadcaster import broadcaster
from services.phone import format_phone_display, normalize_contact_phone

router = APIRouter()


def _serialize_contact(c: Contact) -> ContactResponse:
    return ContactResponse(
        id=c.id,
        phone_number=c.phone_number,
        display_phone=format_phone_display(c.phone_number),
        name=c.name,
        notes=c.notes,
        created_at=c.created_at,
        updated_at=c.updated_at,
        deleted_at=c.deleted_at,
    )


def _find_contact(db: Session, key: str) -> Optional[Contact]:
    if key.isdigit() and len(key) <= 9:
        by_id = db.query(Contact).filter(Contact.id == int(key)).first()
        if by_id:
            return by_id
    canonical = normalize_contact_phone(key)
    return db.query(Contact).filter(Contact.phone_number == canonical).first()


@router.get("", response_model=List[ContactResponse])
@router.get("/", response_model=List[ContactResponse])
def get_contacts(
    search: Optional[str] = Query(None, max_length=100),
    include_deleted: bool = False,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    query = db.query(Contact)
    if not include_deleted:
        query = query.filter(Contact.deleted_at.is_(None))
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Contact.name.ilike(term),
                Contact.phone_number.ilike(term),
                Contact.notes.ilike(term),
            )
        )
    rows = query.order_by(Contact.name.asc()).all()
    return [_serialize_contact(c) for c in rows]


@router.post("", response_model=ContactResponse)
@router.post("/", response_model=ContactResponse)
async def create_contact(
    payload: ContactCreate,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    canonical = normalize_contact_phone(payload.phone_number)
    if canonical == "unknown":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Valid phone number is required.")

    existing = db.query(Contact).filter(Contact.phone_number == canonical).first()
    if existing and existing.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A contact with this phone number already exists.")

    now = utc_now()
    if existing and existing.deleted_at is not None:
        existing.name = payload.name.strip()
        existing.notes = payload.notes.strip() if payload.notes else None
        existing.deleted_at = None
        existing.deleted_by_user_id = None
        existing.updated_at = now
        contact = existing
    else:
        contact = Contact(
            phone_number=canonical,
            name=payload.name.strip(),
            notes=payload.notes.strip() if payload.notes else None,
            created_at=now,
            updated_at=now,
        )
        db.add(contact)
    db.flush()

    record_audit(
        db,
        action="contact.created",
        resource_type="contact",
        resource_id=str(contact.id),
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"phone_number": canonical},
        commit=False,
    )
    db.commit()
    db.refresh(contact)

    serialized = _serialize_contact(contact)
    await broadcaster.publish("contact_updated", serialized.model_dump(mode="json"))
    return serialized


@router.put("/{contact_key}", response_model=ContactResponse)
async def update_contact(
    contact_key: str,
    payload: ContactUpdate,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    contact = _find_contact(db, contact_key)
    if not contact or contact.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found.")

    if payload.name is not None:
        contact.name = payload.name.strip()
    if payload.notes is not None:
        contact.notes = payload.notes.strip() if payload.notes.strip() else None
    contact.updated_at = utc_now()

    record_audit(
        db,
        action="contact.updated",
        resource_type="contact",
        resource_id=str(contact.id),
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"phone_number": contact.phone_number},
        commit=False,
    )
    db.commit()
    db.refresh(contact)

    serialized = _serialize_contact(contact)
    await broadcaster.publish("contact_updated", serialized.model_dump(mode="json"))
    return serialized


@router.delete("/{contact_key}")
async def delete_contact(
    contact_key: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    contact = _find_contact(db, contact_key)
    if not contact or contact.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found.")

    contact.deleted_at = utc_now()
    contact.deleted_by_user_id = auth.user.id
    contact.updated_at = utc_now()

    record_audit(
        db,
        action="contact.deleted",
        resource_type="contact",
        resource_id=str(contact.id),
        actor_user=auth.user,
        ip_address=extract_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        metadata={"phone_number": contact.phone_number},
        commit=False,
    )
    db.commit()

    await broadcaster.publish(
        "contact_updated",
        {"phone_number": contact.phone_number, "deleted": True},
    )
    return {"status": "deleted", "phone_number": contact.phone_number}


@router.post("/{contact_key}/restore", response_model=ContactResponse)
async def restore_contact(
    contact_key: str,
    request: Request,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    contact = _find_contact(db, contact_key)
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found.")

    if contact.deleted_at is not None:
        contact.deleted_at = None
        contact.deleted_by_user_id = None
        contact.updated_at = utc_now()
        record_audit(
            db,
            action="contact.restored",
            resource_type="contact",
            resource_id=str(contact.id),
            actor_user=auth.user,
            ip_address=extract_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            metadata={"phone_number": contact.phone_number},
            commit=False,
        )
        db.commit()
        db.refresh(contact)

    serialized = _serialize_contact(contact)
    await broadcaster.publish("contact_updated", serialized.model_dump(mode="json"))
    return serialized
