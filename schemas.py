from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

# --- CONTACTS ---
class ContactBase(BaseModel):
    phone_number: str
    name: str
    notes: Optional[str] = None

class ContactCreate(ContactBase):
    pass

class ContactUpdate(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None

class ContactResponse(ContactBase):
    class Config:
        from_attributes = True

# --- ATTACHMENTS ---
class AttachmentBase(BaseModel):
    filename: str
    content_type: Optional[str] = None

    class Config:
        from_attributes = True

# --- MESSAGES ---
class MessageSend(BaseModel):
    recipient: str
    body: Optional[str] = ""
    # We leave this open in case you eventually want to send media from the web UI
    media_urls: List[str] = [] 

class MessageResponse(BaseModel):
    id: str  
    message_id: Optional[str] = None
    sender: Optional[str] = None
    recipient: Optional[str] = None
    body: str
    timestamp: datetime
    
    # Status Flags
    is_sent: bool
    is_delivered: bool
    is_read: bool
    is_failed: bool
    is_cancelled: bool
    web_viewed: bool
    error_reason: Optional[str] = None
    
    attachments: List[AttachmentBase] = []

    class Config:
        from_attributes = True

# --- WEBHOOKS ---
class RawWebhookCreate(BaseModel):
    payload: str