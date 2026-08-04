from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime, timezone
from database import Base
import uuid

class Contact(Base):
    __tablename__ = "contacts"

    phone_number = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)

class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    gateway_id = Column(String, unique=True, index=True, nullable=True) # Native Android ID
    raw_number = Column(String, index=True, nullable=False)
    body = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    is_inbound = Column(Boolean, default=True)
    status = Column(String, default="delivered")