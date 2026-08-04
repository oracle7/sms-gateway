from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models, schemas

router = APIRouter(prefix="/contacts", tags=["Contacts"])

@router.get("/", response_model=List[schemas.ContactResponse])
def get_contacts(db: Session = Depends(get_db)):
    return db.query(models.Contact).order_by(models.Contact.name).all()

@router.post("/", response_model=schemas.ContactResponse)
def create_contact(contact: schemas.ContactCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Contact).filter(models.Contact.phone_number == contact.phone_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Contact with this number already exists.")
    
    db_contact = models.Contact(phone_number=contact.phone_number, name=contact.name)
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    return db_contact

@router.delete("/{phone_number}")
def delete_contact(phone_number: str, db: Session = Depends(get_db)):
    contact = db.query(models.Contact).filter(models.Contact.phone_number == phone_number).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    db.delete(contact)
    db.commit()
    return {"status": "success", "detail": "Contact deleted"}