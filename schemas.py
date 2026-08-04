from typing import Optional
from pydantic import BaseModel
from datetime import datetime

class ContactBase(BaseModel):
    phone_number: str
    name: str

class ContactCreate(ContactBase):
    pass

class ContactResponse(ContactBase):
    class Config:
        from_attributes = True

class MessageSend(BaseModel):
    recipient: str
    body: str

class MessageResponse(BaseModel):
    id: str  
    raw_number: str
    body: str
    timestamp: datetime
    is_inbound: bool
    status: Optional[str] = None

    class Config:
        from_attributes = True