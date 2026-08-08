from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from database import get_db
import models, schemas

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

@router.get("/", response_model=List[schemas.ContactResponse])
def get_contacts(
    search: Optional[str] = None, 
    db: Session = Depends(get_db)
):
    """Fetches all contacts. Optionally filter by name or phone number."""
    query = db.query(models.Contact)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (models.Contact.name.ilike(search_term)) | 
            (models.Contact.phone_number.ilike(search_term))
        )
    return query.order_by(models.Contact.name.asc()).all()

@router.post("/", response_model=schemas.ContactResponse)
def create_contact(contact: schemas.ContactCreate, db: Session = Depends(get_db)):
    """Adds a new contact to the database."""
    existing = db.query(models.Contact).filter(models.Contact.phone_number == contact.phone_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Contact with this phone number already exists.")
    
    new_contact = models.Contact(
        phone_number=contact.phone_number,
        name=contact.name,
        notes=contact.notes
    )
    db.add(new_contact)
    db.commit()
    db.refresh(new_contact)
    return new_contact

@router.put("/{phone_number}", response_model=schemas.ContactResponse)
def update_contact(phone_number: str, contact_update: schemas.ContactUpdate, db: Session = Depends(get_db)):
    """Updates an existing contact's name or notes."""
    existing = db.query(models.Contact).filter(models.Contact.phone_number == phone_number).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Contact not found.")
    
    if contact_update.name is not None:
        existing.name = contact_update.name
    if contact_update.notes is not None:
        existing.notes = contact_update.notes
        
    db.commit()
    db.refresh(existing)
    return existing

@router.delete("/{phone_number}")
def delete_contact(phone_number: str, db: Session = Depends(get_db)):
    """
    Deletes a contact from the address book.
    Does NOT affect message history in the messages table.
    """
    existing = db.query(models.Contact).filter(models.Contact.phone_number == phone_number).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Contact not found.")
    
    db.delete(existing)
    db.commit()
    return {"status": "success", "message": "Contact deleted successfully."}