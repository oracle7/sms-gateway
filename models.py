from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, CheckConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import uuid

# Assuming you have a database.py with `Base` defined
from database import Base

class Contact(Base):
    __tablename__ = "contacts"

    phone_number = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    notes = Column(Text, nullable=True)

class Message(Base):
    __tablename__ = "messages"
    
    # The strict ghost-blocking constraint
    __table_args__ = (
        CheckConstraint(
            'sender IS NOT NULL OR recipient IS NOT NULL', 
            name='chk_sender_recipient_not_null'
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id = Column(String, unique=True, index=True, nullable=True) # Native Android gateway ID
    
    sender = Column(String, index=True, nullable=True)
    recipient = Column(String, index=True, nullable=True)
    body = Column(String, nullable=False, default="")
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    
    # Status Booleans
    is_sent = Column(Boolean, default=False)
    is_delivered = Column(Boolean, default=False)
    is_read = Column(Boolean, default=False)
    is_failed = Column(Boolean, default=False)
    is_cancelled = Column(Boolean, default=False)
    web_viewed = Column(Boolean, default=False)
    
    # Error debug log
    error_reason = Column(Text, nullable=True)

    attachments = relationship("MessageAttachment", backref="message", cascade="all, delete-orphan")

class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    message_id = Column(String, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)

class RawWebhookDump(Base):
    __tablename__ = "raw_webhooks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    payload = Column(Text, nullable=False)