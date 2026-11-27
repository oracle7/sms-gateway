from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


# --- AUTH & USERS ---
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: Literal["admin", "staff"]
    is_active: bool
    must_change_password: bool
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None


class MeResponse(BaseModel):
    user: UserPublic
    csrf_token: str
    idle_expires_at: datetime
    idle_timeout_seconds: int
    build_id: str
    app_version: str


class HeartbeatResponse(BaseModel):
    idle_expires_at: datetime
    idle_timeout_seconds: int


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)
    revoke_other_sessions: bool = True


class SessionPublic(BaseModel):
    id: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    is_current: bool = False


# --- CONTACTS ---
class ContactCreate(BaseModel):
    phone_number: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=160)
    notes: Optional[str] = None


class ContactUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    notes: Optional[str] = None


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone_number: str
    display_phone: str = ""
    name: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None


# --- ATTACHMENTS & MESSAGES ---
class AttachmentResponse(BaseModel):
    id: int
    filename: str
    original_filename: Optional[str] = None
    content_type: str
    size_bytes: Optional[int] = None
    url: str


class MessageSendRequest(BaseModel):
    recipient: str = Field(min_length=1, max_length=32)
    body: str = Field(min_length=1, max_length=4000)


class MessageResponse(BaseModel):
    id: str
    gateway_message_id: Optional[str] = None
    contact_phone: str
    direction: Literal["inbound", "outbound"]
    sender: str
    recipient: str
    body: str
    timestamp: datetime
    sent_by_user_id: Optional[int] = None
    sent_by_display_name: Optional[str] = None
    status: str
    is_sent: bool
    is_delivered: bool
    is_failed: bool
    is_cancelled: bool
    error_reason: Optional[str] = None
    read_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    attachments: List[AttachmentResponse] = []


# --- THREADS ---
class ThreadResponse(BaseModel):
    contact_phone: str
    display_phone: str
    contact_name: Optional[str] = None
    contact_notes: Optional[str] = None
    last_message_id: Optional[str] = None
    last_message_at: Optional[datetime] = None
    last_message_preview: str = ""
    last_message_direction: Optional[str] = None
    unread_count: int = 0
    archived_at: Optional[datetime] = None


class ThreadListResponse(BaseModel):
    items: List[ThreadResponse]
    total: int
    total_unread_active: int
    limit: int
    offset: int
    has_more: bool


class MessagePageResponse(BaseModel):
    thread: ThreadResponse
    items: List[MessageResponse]
    has_more: bool
    next_before_ts: Optional[datetime] = None
    next_before_id: Optional[str] = None


# --- ADMIN ---
class AdminUserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    role: Literal["admin", "staff"] = "staff"
    password: str = Field(min_length=1, max_length=256)
    must_change_password: bool = False


class AdminUserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    role: Optional[Literal["admin", "staff"]] = None
    is_active: Optional[bool] = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=1, max_length=256)
    must_change_password: bool = True


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    outcome: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    metadata_json: Optional[str] = None
    prev_hash: str
    row_hash: str


class AuditLogPageResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int
    limit: int
    offset: int


class AuditChainVerifyResponse(BaseModel):
    valid: bool
    total_rows: int
    first_broken_id: Optional[int] = None
    error: Optional[str] = None


# --- HEALTH & SYSTEM ---
class HealthStatusResponse(BaseModel):
    status: str
    battery_level: object = "--"
    is_charging: bool = False
    last_updated_at: Optional[datetime] = None
